"""The single asynchronous attempt loop of the whole library.

Order is baked in and not configurable:
deadline -> headers -> per-origin slot -> circuit check (outside retry)
-> [hop loop -> attempt loop] -> circuit record (one signal) -> telemetry end.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from typing import Any

from ..contracts.adapter import AdapterDeps
from ..contracts.message import AsyncNormalizer, RequestView, ResponseView
from ..errors import AttemptTimeoutError, CallError, CircuitOpenError, DeadlineExceededError, TooManyRedirectsError
from ..model import Attempt, FailureKind, Outcome, RequestInfo
from ..plan import CallPlan, ClientRuntime
from ..policy.budget import Deadline
from ..telemetry.emitter import CallObservation, ClientTelemetry
from .base import SKIP_REASONS, deadline_header_value, inject_static_headers
from .redirects import apply_redirect, plan_redirect

type AsyncSend = Callable[[RequestView], Awaitable[Any]]
type ErrorTranslator = Callable[[CallError], BaseException]

logger = logging.getLogger("clientwright.engine")


class AsyncAttemptEngine:
    """Runs one logical call: retries, owned redirects, deadline, telemetry."""

    def __init__(
        self,
        *,
        plan: CallPlan,
        runtime: ClientRuntime,
        telemetry: ClientTelemetry,
        normalizer: AsyncNormalizer,
        deps: AdapterDeps,
        translate: ErrorTranslator,
    ) -> None:
        self._plan = plan
        self._runtime = runtime
        self._telemetry = telemetry
        self._norm = normalizer
        self._deps = deps
        self._translate = translate

    async def run(self, native_request: Any, send: AsyncSend) -> Any:
        clock = self._runtime.clock
        request = self._norm.wrap_request(native_request)
        info = request.info
        started = clock()
        observation = self._telemetry.call_start(info, started)
        final_outcome = Outcome(kind=FailureKind.UNKNOWN)
        response: ResponseView | None = None
        try:
            response, final_outcome = await self._admitted(request, send, observation)
        except CallError as error:
            final_outcome = self._call_error_outcome(error)
            raise self._translate(error) from error
        except BaseException as error:
            if final_outcome.exception is not error:
                final_outcome = Outcome(kind=self._norm.classify_error(error), exception=error)
            raise
        finally:
            self._telemetry.call_end(observation, info, final_outcome, clock() - started)
        if final_outcome.exception is not None:
            raise final_outcome.exception
        assert response is not None  # a call without exception always has a response
        self._wrap_stream(response, info)
        return response.native

    def _call_error_outcome(self, error: CallError) -> Outcome:
        if isinstance(error, CircuitOpenError):
            return Outcome(kind=FailureKind.CIRCUIT_OPEN, exception=error)
        if isinstance(error, DeadlineExceededError):
            return Outcome(kind=FailureKind.TOTAL_TIMEOUT, exception=error)
        if isinstance(error, AttemptTimeoutError):
            return Outcome(kind=FailureKind.ATTEMPT_TIMEOUT, exception=error)
        return Outcome(kind=FailureKind.UNKNOWN, exception=error)

    def _wrap_stream(self, response: ResponseView, info: Any) -> None:
        def on_done(outcome: Outcome, duration: float) -> None:
            self._telemetry.record_body_duration(info, duration)

        self._norm.wrap_stream(response, on_done)

    def _inject_headers(self, request: RequestView) -> None:
        headers = request.headers
        inject_static_headers(headers, dict(self._plan.config.headers))
        for provider in self._deps.header_providers:
            try:
                inject_static_headers(headers, dict(provider()))
            except Exception:
                logger.debug("Header provider %r failed", provider, exc_info=True)
                continue
        self._telemetry.tracer.inject_context(headers)

    def _deadline(self, request: RequestView) -> Deadline:
        ambient = self._deps.deadline_source.remaining() if self._deps.deadline_source is not None else None
        return Deadline.intersect(self._runtime.clock, self._plan.config.timeout.total, ambient)

    async def _admitted(
        self, request: RequestView, send: AsyncSend, observation: CallObservation
    ) -> tuple[ResponseView | None, Outcome]:
        plan = self._plan
        runtime = self._runtime
        info = request.info
        deadline = self._deadline(request)
        self._inject_headers(request)
        circuit_key: str | None = None
        async with AsyncExitStack() as stack:
            if plan.use_origin_limiter and runtime.async_limiter is not None:
                await stack.enter_async_context(runtime.async_limiter.acquire(info.origin))
            if runtime.circuits is not None and plan.config.circuit_breaker is not None:
                circuit_key = info.circuit_key(plan.config.circuit_breaker.key)
                runtime.circuits.check(circuit_key)
            if runtime.retry_budgets is not None:
                runtime.retry_budgets.earn(info.origin)
            outcome = Outcome(kind=FailureKind.UNKNOWN)
            aborted = False
            try:
                response, outcome = await self._hops(request, send, deadline, observation)
            except CallError as error:
                outcome = self._call_error_outcome(error)
                raise
            except BaseException:
                # Cancellation or an adapter fault: no classified outcome, so it
                # must be neither a success nor a failure signal for the breaker.
                aborted = True
                raise
            else:
                return response, outcome
            finally:
                if circuit_key is not None and runtime.circuits is not None:
                    if aborted:
                        runtime.circuits.record_aborted(circuit_key)
                    else:
                        runtime.circuits.record(circuit_key, outcome)
        raise AssertionError("unreachable")  # pragma: no cover - AsyncExitStack never swallows

    async def _hops(
        self, request: RequestView, send: AsyncSend, deadline: Deadline, observation: CallObservation
    ) -> tuple[ResponseView | None, Outcome]:
        plan = self._plan
        replayable = await self._freeze_if_needed(request)
        history: list[Attempt] = []
        while True:
            response, outcome = await self._attempts(request, send, deadline, observation, history, replayable)
            if response is None or outcome.exception is not None:
                return response, outcome
            if plan.config.redirects.value != "owned":
                return response, outcome
            step = plan_redirect(response, request)
            if step is None:
                return response, outcome
            if observation.hops >= plan.config.max_redirects:
                raise TooManyRedirectsError(plan.config.max_redirects)
            if step.needs_body_replay and not replayable:
                return response, outcome
            await self._norm.discard(response)
            apply_redirect(request, step)
            self._telemetry.redirect_hop(observation)

    async def _freeze_if_needed(self, request: RequestView) -> bool:
        plan = self._plan
        needs_replay = plan.retry_policy is not None or plan.config.redirects.value == "owned"
        if not needs_replay:
            return True
        return await self._norm.freeze(request)

    def _retry_delay(
        self, info: RequestInfo, history: list[Attempt], deadline: Deadline, replayable: bool
    ) -> float | None:
        """Backoff before the next attempt, or None when the last outcome is final."""
        plan = self._plan
        runtime = self._runtime
        if plan.retry_policy is None:
            return None
        decision = plan.retry_policy.decide(
            info=info,
            history=history,
            remaining=deadline.remaining(),
            replayable=replayable,
            rng=runtime.rng,
        )
        if not decision.retry:
            if decision.reason in SKIP_REASONS:
                self._telemetry.retry_skipped(decision.reason)
            return None
        if runtime.retry_budgets is not None and not runtime.retry_budgets.try_spend(info.origin):
            self._telemetry.retry_skipped("budget")
            return None
        return decision.delay

    async def _attempts(
        self,
        request: RequestView,
        send: AsyncSend,
        deadline: Deadline,
        observation: CallObservation,
        history: list[Attempt],
        replayable: bool,
    ) -> tuple[ResponseView | None, Outcome]:
        plan = self._plan
        runtime = self._runtime
        info = request.info
        caller = request.caller_timeouts()
        while True:
            remaining = deadline.remaining()
            if remaining is not None and remaining <= 0:
                raise DeadlineExceededError(deadline.total or 0.0)
            timeouts = plan.planner.plan(remaining=remaining, caller=caller)
            request.apply_timeouts(timeouts)
            if plan.config.deadline_header is not None and remaining is not None:
                request.headers[plan.config.deadline_header] = deadline_header_value(remaining)
            attempt_started = runtime.clock()
            observation.attempts += 1
            response: ResponseView | None = None
            ceiling = asyncio.timeout(timeouts.attempt)
            try:
                async with ceiling:
                    native_response = await send(request)
                response = self._norm.wrap_response(native_response)
                outcome = self._norm.classify_response(response)
            except CallError:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # Only a fired ceiling is the engine's own timeout. Matching on
                # TimeoutError would also swallow the SDK's: aiohttp's whole
                # timeout family subclasses it.
                if not ceiling.expired():
                    kind = self._norm.classify_error(error)
                elif deadline.expired:
                    kind = FailureKind.TOTAL_TIMEOUT
                else:
                    kind = FailureKind.ATTEMPT_TIMEOUT
                outcome = Outcome(kind=kind, exception=error)
            attempt = Attempt(
                index=len(history) + 1,
                started=attempt_started,
                duration=runtime.clock() - attempt_started,
                outcome=outcome,
                hop=observation.hops,
                conn=self._norm.conn_metrics(response) if response is not None else None,
            )
            history.append(attempt)
            if plan.emit_attempt_metrics:
                self._telemetry.attempt_end(observation, info, attempt)
            if outcome.kind is FailureKind.TOTAL_TIMEOUT and deadline.expired:
                raise DeadlineExceededError(deadline.total or 0.0) from outcome.exception
            delay = self._retry_delay(info, history, deadline, replayable)
            if delay is None:
                if outcome.kind is FailureKind.ATTEMPT_TIMEOUT:
                    raise AttemptTimeoutError(timeouts.attempt or 0.0) from outcome.exception
                return response, outcome
            if response is not None:
                await self._norm.discard(response)
            await self._norm.rewind(request)
            if delay > 0:
                await asyncio.sleep(delay)


__all__ = ["AsyncAttemptEngine", "AsyncSend", "ErrorTranslator"]
