"""The single synchronous attempt loop; mirrors AsyncAttemptEngine.

Sync runtimes cannot cancel a blocked socket call, so the total deadline is
SOFT here: per-attempt phases are clamped by the remaining budget and the
deadline is re-checked at attempt boundaries. Adapters declare this as
``DEADLINE_HARD: ABSENT``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import ExitStack
from typing import Any

from ..contracts.adapter import AdapterDeps
from ..contracts.message import RequestView, ResponseView, SyncNormalizer
from ..errors import CallError, CircuitOpenError, DeadlineExceededError, TooManyRedirectsError
from ..model import Attempt, FailureKind, Outcome
from ..plan import CallPlan, ClientRuntime
from ..policy.budget import Deadline
from ..telemetry.emitter import CallObservation, ClientTelemetry
from .base import SKIP_REASONS, deadline_header_value, inject_static_headers
from .redirects import apply_redirect, plan_redirect

type SyncSend = Callable[[RequestView], Any]
type ErrorTranslator = Callable[[CallError], BaseException]

logger = logging.getLogger("clientwright.engine")


class SyncAttemptEngine:
    def __init__(
        self,
        *,
        plan: CallPlan,
        runtime: ClientRuntime,
        telemetry: ClientTelemetry,
        normalizer: SyncNormalizer,
        deps: AdapterDeps,
        translate: ErrorTranslator,
    ) -> None:
        self._plan = plan
        self._runtime = runtime
        self._telemetry = telemetry
        self._norm = normalizer
        self._deps = deps
        self._translate = translate

    def run(self, native_request: Any, send: SyncSend) -> Any:
        clock = self._runtime.clock
        request = self._norm.wrap_request(native_request)
        info = request.info
        started = clock()
        observation = self._telemetry.call_start(info, started)
        final_outcome = Outcome(kind=FailureKind.UNKNOWN)
        response: ResponseView | None = None
        try:
            response, final_outcome = self._admitted(request, send, observation)
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
        assert response is not None
        self._wrap_stream(response, info)
        return response.native

    def _call_error_outcome(self, error: CallError) -> Outcome:
        if isinstance(error, CircuitOpenError):
            return Outcome(kind=FailureKind.CIRCUIT_OPEN, exception=error)
        if isinstance(error, DeadlineExceededError):
            return Outcome(kind=FailureKind.TOTAL_TIMEOUT, exception=error)
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

    def _deadline(self) -> Deadline:
        ambient = self._deps.deadline_source.remaining() if self._deps.deadline_source is not None else None
        return Deadline.intersect(self._runtime.clock, self._plan.config.timeout.total, ambient)

    def _admitted(
        self, request: RequestView, send: SyncSend, observation: CallObservation
    ) -> tuple[ResponseView | None, Outcome]:
        plan = self._plan
        runtime = self._runtime
        info = request.info
        deadline = self._deadline()
        self._inject_headers(request)
        circuit_key: str | None = None
        with ExitStack() as stack:
            if plan.use_origin_limiter and runtime.sync_limiter is not None:
                stack.enter_context(runtime.sync_limiter.acquire(info.origin))
            if runtime.circuits is not None and plan.config.circuit_breaker is not None:
                circuit_key = info.circuit_key(plan.config.circuit_breaker.key)
                runtime.circuits.check(circuit_key)
            if runtime.retry_budgets is not None:
                runtime.retry_budgets.earn(info.origin)
            outcome = Outcome(kind=FailureKind.UNKNOWN)
            aborted = False
            try:
                response, outcome = self._hops(request, send, deadline, observation)
            except CallError as error:
                outcome = self._call_error_outcome(error)
                raise
            except BaseException:
                # No classified outcome: neither success nor failure for the breaker.
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
        raise AssertionError("unreachable")  # pragma: no cover - ExitStack never swallows

    def _hops(
        self, request: RequestView, send: SyncSend, deadline: Deadline, observation: CallObservation
    ) -> tuple[ResponseView | None, Outcome]:
        plan = self._plan
        replayable = self._freeze_if_needed(request)
        history: list[Attempt] = []
        while True:
            response, outcome = self._attempts(request, send, deadline, observation, history, replayable)
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
            self._norm.discard(response)
            apply_redirect(request, step)
            self._telemetry.redirect_hop(observation)

    def _freeze_if_needed(self, request: RequestView) -> bool:
        plan = self._plan
        needs_replay = plan.retry_policy is not None or plan.config.redirects.value == "owned"
        if not needs_replay:
            return True
        return self._norm.freeze(request)

    def _attempts(
        self,
        request: RequestView,
        send: SyncSend,
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
            try:
                native_response = send(request)
                response = self._norm.wrap_response(native_response)
                outcome = self._norm.classify_response(response)
            except CallError:
                raise
            except TimeoutError as error:
                outcome = Outcome(kind=FailureKind.TOTAL_TIMEOUT, exception=error)
            except Exception as error:
                outcome = Outcome(kind=self._norm.classify_error(error), exception=error)
            attempt = Attempt(
                index=len(history) + 1,
                started=attempt_started,
                duration=runtime.clock() - attempt_started,
                outcome=outcome,
                hop=observation.hops,
            )
            history.append(attempt)
            if plan.emit_attempt_metrics:
                self._telemetry.attempt_end(info, attempt)
            if outcome.kind is FailureKind.TOTAL_TIMEOUT and deadline.expired:
                raise DeadlineExceededError(deadline.total or 0.0) from outcome.exception
            if plan.retry_policy is None:
                return response, outcome
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
                return response, outcome
            if runtime.retry_budgets is not None and not runtime.retry_budgets.try_spend(info.origin):
                self._telemetry.retry_skipped("budget")
                return response, outcome
            if response is not None:
                self._norm.discard(response)
            self._norm.rewind(request)
            if decision.delay > 0:
                time.sleep(decision.delay)


__all__ = ["SyncAttemptEngine", "SyncSend"]
