"""Engine test harness: scripted sends, fake normalizers and builders.

The engines are exercised here without any SDK: the fakes implement the
``RequestView``/``ResponseView``/normalizer contracts directly, so every branch
of the attempt loop is reachable deterministically.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from clientwright.core.capabilities import (
    AdapterCapabilities,
    Capability,
    DurationBoundary,
    SeamGranularity,
    Support,
)
from clientwright.core.config import ClientConfig, RetryConfig
from clientwright.core.contracts.adapter import AdapterDeps
from clientwright.core.engine.aio import AsyncAttemptEngine
from clientwright.core.engine.base import default_response_outcome
from clientwright.core.engine.sync import SyncAttemptEngine
from clientwright.core.model import FailureKind, Outcome, RequestInfo, ResolvedTimeouts, origin_of
from clientwright.core.plan import ClientRuntime, compile_plan
from clientwright.core.telemetry.emitter import ClientTelemetry
from clientwright.core.testing import RecordingMetrics
from tests.helpers.views import FakeResponse

FAKE_CAPABILITIES = AdapterCapabilities(
    adapter="fake",
    seam="test",
    granularity=SeamGranularity.LOGICAL,
    boundary=DurationBoundary.HEADERS,
    support={Capability.POOL_LIMIT_PER_HOST: Support.EMULATED},
    emits=frozenset(FailureKind),
)

NATIVE_DEFAULTS = ResolvedTimeouts(connect=5.0, read=5.0, write=5.0, pool_acquire=5.0)


def fast_retry(**overrides: object) -> RetryConfig:
    """Retry config with near-zero deterministic backoff for engine tests."""
    defaults: dict[str, object] = {"jitter": 0.0, "initial_backoff": 0.001, "max_backoff": 0.001}
    defaults.update(overrides)
    return RetryConfig(**defaults)  # type: ignore[arg-type]


def make_config(**overrides: object) -> ClientConfig:
    defaults: dict[str, object] = {
        "service_name": "engine-test",
        "retry": fast_retry(),
        "circuit_breaker": None,
    }
    defaults.update(overrides)
    return ClientConfig(**defaults)  # type: ignore[arg-type]


def redirect_response(url: str) -> FakeResponse:
    """A 302 response pointing at ``url``."""
    return FakeResponse(302, {"Location": url})


class FixedDeadlineSource:
    """DeadlineSource double returning a constant remaining budget."""

    def __init__(self, remaining: float | None) -> None:
        self._remaining = remaining

    def remaining(self) -> float | None:
        return self._remaining


class EngineRequest:
    """RequestView fake whose retarget actually rewrites the request identity."""

    def __init__(
        self,
        method: str = "GET",
        url: str = "http://a.example/x",
        *,
        route: str | None = None,
        idempotent: bool = True,
        headers: dict[str, str] | None = None,
        caller: ResolvedTimeouts | None = None,
    ) -> None:
        self.method = method
        self.url = url
        self.headers: dict[str, str] = dict(headers or {})
        self.caller = caller
        self.applied_timeouts: list[ResolvedTimeouts] = []
        self.retargets: list[str] = []
        self.body_dropped = False
        self._route = route
        self._idempotent = idempotent

    @property
    def native(self) -> EngineRequest:
        return self

    @property
    def info(self) -> RequestInfo:
        return RequestInfo(
            method=self.method,
            origin=origin_of(self.url),
            url=self.url,
            route=self._route,
            idempotent=self._idempotent,
        )

    def caller_timeouts(self) -> ResolvedTimeouts | None:
        return self.caller

    def apply_timeouts(self, timeouts: ResolvedTimeouts) -> None:
        self.applied_timeouts.append(timeouts)

    def retarget(self, url: str, *, method: str | None = None, drop_body: bool = False) -> None:
        self.url = url
        if method is not None:
            self.method = method
        if drop_body:
            self.body_dropped = True
        self.retargets.append(url)


@dataclass
class Slow:
    """Scripted step that stalls before yielding its inner step."""

    delay: float
    then: object


class ScriptedSend:
    """Send double: one scripted step per physical attempt, in order."""

    def __init__(self, *steps: object) -> None:
        self._steps = list(steps)
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    @property
    def sent(self) -> int:
        return len(self.calls)

    def next_step(self, request: EngineRequest) -> object:
        self.calls.append((request.info.method, request.info.url, dict(request.headers)))
        if not self._steps:
            raise AssertionError("ScriptedSend exhausted: more attempts than scripted steps")
        return self._steps.pop(0)


def as_sync_send(script: ScriptedSend) -> Callable[[EngineRequest], Any]:
    def send(request: EngineRequest) -> Any:
        step = script.next_step(request)
        if isinstance(step, Slow):
            time.sleep(step.delay)
            step = step.then
        if isinstance(step, BaseException):
            raise step
        return step

    return send


def as_async_send(script: ScriptedSend) -> Callable[[EngineRequest], Any]:
    async def send(request: EngineRequest) -> Any:
        step = script.next_step(request)
        if isinstance(step, Slow):
            await asyncio.sleep(step.delay)
            step = step.then
        if isinstance(step, BaseException):
            raise step
        return step

    return send


class FakeNormalizer:
    """Both normalizer flavors in one object; the request/response ARE the views."""

    def __init__(self, *, freeze_ok: bool = True) -> None:
        self.freeze_ok = freeze_ok
        self.freezes = 0
        self.rewinds = 0
        self.discards = 0
        self.wrapped_streams = 0

    def wrap_request(self, native: Any) -> EngineRequest:
        assert isinstance(native, EngineRequest)
        return native

    def wrap_response(self, native: Any) -> FakeResponse:
        assert isinstance(native, FakeResponse)
        return native

    def classify_error(self, exc: BaseException) -> FailureKind:
        if isinstance(exc, asyncio.CancelledError):
            return FailureKind.CANCELLED
        if isinstance(exc, TimeoutError):
            return FailureKind.READ_TIMEOUT
        if isinstance(exc, ConnectionError):
            return FailureKind.CONNECT_ERROR
        return FailureKind.UNKNOWN

    def classify_response(self, response: FakeResponse) -> Outcome:
        return default_response_outcome(response)

    def wrap_stream(self, response: FakeResponse, on_done: Callable[[Outcome, float], None]) -> None:
        self.wrapped_streams += 1

    def conn_metrics(self, response: FakeResponse) -> None:
        return None

    # -- sync flavor -------------------------------------------------------

    def _freeze(self, request: EngineRequest) -> bool:
        self.freezes += 1
        return self.freeze_ok

    def _rewind(self, request: EngineRequest) -> None:
        self.rewinds += 1

    def _discard(self, response: FakeResponse) -> None:
        self.discards += 1


class FakeSyncNormalizer(FakeNormalizer):
    def freeze(self, request: EngineRequest) -> bool:
        return self._freeze(request)

    def rewind(self, request: EngineRequest) -> None:
        self._rewind(request)

    def discard(self, response: FakeResponse) -> None:
        self._discard(response)


class FakeAsyncNormalizer(FakeNormalizer):
    async def freeze(self, request: EngineRequest) -> bool:
        return self._freeze(request)

    async def rewind(self, request: EngineRequest) -> None:
        self._rewind(request)

    async def discard(self, response: FakeResponse) -> None:
        self._discard(response)


class Harness:
    """A compiled plan, runtime and telemetry around one engine instance."""

    def __init__(
        self,
        config: ClientConfig,
        *,
        deps: AdapterDeps | None = None,
        freeze_ok: bool = True,
        sync: bool = False,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self.metrics = RecordingMetrics()
        self.deps = deps or AdapterDeps()
        self.runtime = ClientRuntime.for_config(config, clock=clock)
        self.plan = compile_plan(config, FAKE_CAPABILITIES, native_timeout_defaults=NATIVE_DEFAULTS)
        self.telemetry = ClientTelemetry(
            service=config.service_name,
            adapter="fake",
            seam="test",
            config=config.observability,
            metrics=self.metrics,
            tracer=None,
        )
        self.normalizer: FakeSyncNormalizer | FakeAsyncNormalizer
        if sync:
            self.normalizer = FakeSyncNormalizer(freeze_ok=freeze_ok)
            self.engine: Any = SyncAttemptEngine(
                plan=self.plan,
                runtime=self.runtime,
                telemetry=self.telemetry,
                normalizer=self.normalizer,
                deps=self.deps,
                translate=lambda error: error,
            )
        else:
            self.normalizer = FakeAsyncNormalizer(freeze_ok=freeze_ok)
            self.engine = AsyncAttemptEngine(
                plan=self.plan,
                runtime=self.runtime,
                telemetry=self.telemetry,
                normalizer=self.normalizer,
                deps=self.deps,
                translate=lambda error: error,
            )

    @property
    def call_outcomes(self) -> list[object]:
        return [record["outcome"] for record in self.metrics.calls]

    @property
    def attempt_outcomes(self) -> list[object]:
        return [record["outcome"] for record in self.metrics.attempts]

    @property
    def skip_reasons(self) -> list[object]:
        return [record["reason"] for record in self.metrics.retry_skips]


__all__ = [
    "FAKE_CAPABILITIES",
    "NATIVE_DEFAULTS",
    "EngineRequest",
    "FakeAsyncNormalizer",
    "FakeNormalizer",
    "FakeSyncNormalizer",
    "FixedDeadlineSource",
    "Harness",
    "ScriptedSend",
    "Slow",
    "as_async_send",
    "as_sync_send",
    "fast_retry",
    "make_config",
]
