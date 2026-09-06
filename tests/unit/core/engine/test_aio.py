"""The async attempt engine end-to-end over fakes: every branch, no SDK, no sockets.

The integration suite proves the engine against real clients; this file pins
the loop's decision points deterministically - admission, retries, redirects,
deadlines, aborts and the telemetry that must survive each of them.
"""

from __future__ import annotations

import asyncio

import pytest

from clientwright.core.config import (
    CircuitBreakerConfig,
    PoolConfig,
    RedirectMode,
    TimeoutConfig,
)
from clientwright.core.contracts.adapter import AdapterDeps
from clientwright.core.errors import (
    AttemptTimeoutError,
    CircuitOpenError,
    DeadlineExceededError,
    TooManyRedirectsError,
)
from clientwright.core.model import ConnMetrics, ResolvedTimeouts
from clientwright.core.policy.circuit import CircuitState
from clientwright.core.testing import ManualClock
from tests.helpers.engine import (
    EngineRequest,
    FixedDeadlineSource,
    Harness,
    ScriptedSend,
    Slow,
    as_async_send,
    fast_retry,
    make_config,
    redirect_response,
)
from tests.helpers.telemetry import RecordingTracer
from tests.helpers.views import FakeResponse

# --- flow ---


async def test__success__returns_native_response_and_closes_telemetry() -> None:
    harness = Harness(make_config())
    script = ScriptedSend(FakeResponse(200))
    result = await harness.engine.run(EngineRequest(), as_async_send(script))
    assert isinstance(result, FakeResponse)
    assert result.status_code == 200
    assert harness.call_outcomes == ["success"]
    assert harness.metrics.calls[0]["status"] == "200"
    assert harness.metrics.inflight_balance == 0
    assert harness.normalizer.wrapped_streams == 1


async def test__503_then_200__retries_discards_and_rewinds() -> None:
    harness = Harness(make_config())
    script = ScriptedSend(FakeResponse(503), FakeResponse(200))
    result = await harness.engine.run(EngineRequest(), as_async_send(script))
    assert result.status_code == 200
    assert harness.attempt_outcomes == ["status", "success"]
    assert harness.call_outcomes == ["success"]
    assert harness.normalizer.discards == 1  # the 503 body went back to the pool
    assert harness.normalizer.rewinds == 1


async def test__headers__static_and_provider_injected_but_caller_wins() -> None:
    def good_provider() -> dict[str, str]:
        return {"x-prov": "p", "x-preset": "provider-should-lose"}

    def bad_provider() -> dict[str, str]:
        raise RuntimeError("provider down")

    config = make_config(headers={"x-static": "s"})
    deps = AdapterDeps(header_providers=(good_provider, bad_provider))
    harness = Harness(config, deps=deps)
    script = ScriptedSend(FakeResponse(200))
    request = EngineRequest(headers={"x-preset": "caller"})
    await harness.engine.run(request, as_async_send(script))
    _, _, sent_headers = script.calls[0]
    assert sent_headers["x-static"] == "s"
    assert sent_headers["x-prov"] == "p"
    assert sent_headers["x-preset"] == "caller"  # setdefault semantics: caller always wins


async def test__caller_timeouts__reach_the_planner() -> None:
    harness = Harness(make_config())
    script = ScriptedSend(FakeResponse(200))
    request = EngineRequest(caller=ResolvedTimeouts(connect=1.5))
    await harness.engine.run(request, as_async_send(script))
    assert request.applied_timeouts[0].connect == 1.5  # caller_wins default


# --- deadline ---


async def test__ambient_budget_pre_expired__raises_before_any_send() -> None:
    deps = AdapterDeps(deadline_source=FixedDeadlineSource(0.0))
    harness = Harness(make_config(), deps=deps)
    script = ScriptedSend()
    with pytest.raises(DeadlineExceededError):
        await harness.engine.run(EngineRequest(), as_async_send(script))
    assert script.sent == 0
    assert harness.call_outcomes == ["total_timeout"]


async def test__attempt_ceiling_with_budget_left__retried_then_attempt_timeout_error() -> None:
    # The deadline clock is manual and never advances: every ceiling fires with
    # the whole total still available, so each one is a retryable attempt.
    config = make_config(timeout=TimeoutConfig(total=30.0, attempt=0.05))
    harness = Harness(config, clock=ManualClock())
    stall = Slow(1.0, FakeResponse(200))
    script = ScriptedSend(stall, stall, stall)
    with pytest.raises(AttemptTimeoutError) as excinfo:
        await harness.engine.run(EngineRequest(), as_async_send(script))
    assert excinfo.value.attempt == 0.05
    assert script.sent == 3
    assert harness.attempt_outcomes == ["attempt_timeout"] * 3
    assert harness.call_outcomes == ["attempt_timeout"]


async def test__attempt_ceiling_without_a_total__attempt_timeout_error() -> None:
    config = make_config(retry=None, timeout=TimeoutConfig(total=None, attempt=0.05))
    harness = Harness(config)
    script = ScriptedSend(Slow(1.0, FakeResponse(200)))
    with pytest.raises(AttemptTimeoutError):
        await harness.engine.run(EngineRequest(), as_async_send(script))
    assert harness.call_outcomes == ["attempt_timeout"]


async def test__sdk_timeout_subclass__classified_by_the_adapter_not_as_the_ceiling() -> None:
    # aiohttp's whole timeout family subclasses TimeoutError: without a fired
    # ceiling the exception is the SDK's and keeps the adapter's classification.
    harness = Harness(make_config(timeout=TimeoutConfig(total=30.0, attempt=5.0)))
    script = ScriptedSend(TimeoutError("sock_read"), FakeResponse(200))
    result = await harness.engine.run(EngineRequest(), as_async_send(script))
    assert result.status_code == 200
    assert harness.attempt_outcomes == ["read_timeout", "success"]  # the fake normalizer's mapping, retried


async def test__total_deadline_exhausted_mid_attempt__deadline_error() -> None:
    clock = ManualClock()
    config = make_config(retry=None, timeout=TimeoutConfig(total=0.05))
    harness = Harness(config, clock=clock)

    async def stalled_send(request: EngineRequest) -> FakeResponse:
        clock.advance(0.1)  # the attempt burns through the whole total budget...
        await asyncio.sleep(1.0)  # ...and the ceiling, clamped to it, cuts the attempt
        return FakeResponse(200)

    with pytest.raises(DeadlineExceededError):
        await harness.engine.run(EngineRequest(), stalled_send)
    assert harness.call_outcomes == ["total_timeout"]


async def test__deadline_header__stamped_with_remaining_budget() -> None:
    config = make_config(timeout=TimeoutConfig(total=20.0), deadline_header="X-Deadline-Ms")
    harness = Harness(config)
    script = ScriptedSend(FakeResponse(200))
    await harness.engine.run(EngineRequest(), as_async_send(script))
    _, _, sent_headers = script.calls[0]
    assert 0 < int(sent_headers["X-Deadline-Ms"]) <= 20_000


# --- circuit ---


def _breaker_config() -> CircuitBreakerConfig:
    return CircuitBreakerConfig(fail_threshold=1, recovery_timeout=60.0)


async def test__open_circuit__rejects_without_a_send() -> None:
    config = make_config(retry=None, circuit_breaker=_breaker_config())
    harness = Harness(config)
    with pytest.raises(ConnectionError):
        await harness.engine.run(EngineRequest(), as_async_send(ScriptedSend(ConnectionError("boom"))))
    rejected = ScriptedSend()
    with pytest.raises(CircuitOpenError):
        await harness.engine.run(EngineRequest(), as_async_send(rejected))
    assert rejected.sent == 0
    assert harness.call_outcomes == ["connect_error", "circuit_open"]


async def test__cancellation__aborts_the_breaker_instead_of_failing_it() -> None:
    config = make_config(retry=None, circuit_breaker=_breaker_config())
    harness = Harness(config)
    script = ScriptedSend(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await harness.engine.run(EngineRequest(), as_async_send(script))
    assert harness.call_outcomes == ["cancelled"]
    assert harness.runtime.circuits is not None
    snapshot = harness.runtime.circuits.snapshot()
    state = next(iter(snapshot.values()))
    assert state.state is CircuitState.CLOSED
    assert state.failures == 0  # neither success nor failure: an abort


async def test__call_error_from_below__classified_and_trips_the_breaker() -> None:
    config = make_config(retry=None, circuit_breaker=_breaker_config())
    harness = Harness(config)
    script = ScriptedSend(DeadlineExceededError(1.0))
    with pytest.raises(DeadlineExceededError):
        await harness.engine.run(EngineRequest(), as_async_send(script))
    assert harness.call_outcomes == ["total_timeout"]
    with pytest.raises(CircuitOpenError):
        await harness.engine.run(EngineRequest(), as_async_send(ScriptedSend()))


async def test__attempt_timeout_error_from_below__classified_and_trips_the_breaker() -> None:
    config = make_config(retry=None, circuit_breaker=_breaker_config())
    harness = Harness(config)
    script = ScriptedSend(AttemptTimeoutError(0.5))
    with pytest.raises(AttemptTimeoutError):
        await harness.engine.run(EngineRequest(), as_async_send(script))
    assert harness.call_outcomes == ["attempt_timeout"]
    with pytest.raises(CircuitOpenError):
        await harness.engine.run(EngineRequest(), as_async_send(ScriptedSend()))


# --- retry gates ---


async def test__retry_budget_exhausted__returns_response_with_sentinel() -> None:
    harness = Harness(make_config(retry=fast_retry(budget_ratio=0.1)))
    budgets = harness.runtime.retry_budgets
    assert budgets is not None
    origin = EngineRequest().info.origin
    budgets.earn(origin)  # materialize the bucket, then drain its initial burst
    while budgets.try_spend(origin):
        pass  # after this the engine's own earn() refills only 0.1 of a token
    script = ScriptedSend(FakeResponse(503))
    result = await harness.engine.run(EngineRequest(), as_async_send(script))
    assert result.status_code == 503
    assert harness.skip_reasons == ["budget"]


async def test__non_replayable_body__skip_sentinel_instead_of_retry() -> None:
    harness = Harness(make_config(), freeze_ok=False)
    script = ScriptedSend(FakeResponse(503))
    result = await harness.engine.run(EngineRequest(), as_async_send(script))
    assert result.status_code == 503
    assert harness.skip_reasons == ["non_replayable"]


# --- redirects ---


async def test__native_mode__returns_redirect_response_untouched() -> None:
    config = make_config(retry=None, redirects=RedirectMode.NATIVE)
    harness = Harness(config)
    request = EngineRequest()
    result = await harness.engine.run(request, as_async_send(ScriptedSend(redirect_response("/next"))))
    assert result.status_code == 302
    assert request.retargets == []
    assert harness.metrics.redirect_hops == []


async def test__owned_hop__follows_strips_cross_origin_credentials() -> None:
    harness = Harness(make_config())
    request = EngineRequest(
        url="http://a.example/x",
        headers={"authorization": "secret", "cookie": "c=1", "accept": "json"},
    )
    script = ScriptedSend(redirect_response("http://b.example/y"), FakeResponse(200))
    result = await harness.engine.run(request, as_async_send(script))
    assert result.status_code == 200
    assert request.retargets == ["http://b.example/y"]
    _, _, hop_headers = script.calls[1]
    assert "authorization" not in hop_headers
    assert "cookie" not in hop_headers
    assert hop_headers["accept"] == "json"
    assert len(harness.metrics.redirect_hops) == 1
    assert harness.normalizer.discards == 1  # the 302 body was drained before the hop


async def test__redirect_loop__stopped_by_max_redirects() -> None:
    harness = Harness(make_config(max_redirects=2))
    script = ScriptedSend(redirect_response("/a"), redirect_response("/b"), redirect_response("/c"))
    with pytest.raises(TooManyRedirectsError):
        await harness.engine.run(EngineRequest(), as_async_send(script))
    assert script.sent == 3
    assert len(harness.metrics.redirect_hops) == 2


async def test__post_307_without_replayable_body__stops_at_the_redirect() -> None:
    harness = Harness(make_config(), freeze_ok=False)
    request = EngineRequest(method="POST")
    response = FakeResponse(307, {"Location": "/next"})
    result = await harness.engine.run(request, as_async_send(ScriptedSend(response)))
    assert result.status_code == 307  # following would replay a body that cannot be replayed
    assert request.retargets == []


async def test__no_retry_and_native_redirects__freeze_never_called() -> None:
    config = make_config(retry=None, redirects=RedirectMode.NATIVE)
    harness = Harness(config)
    await harness.engine.run(EngineRequest(), as_async_send(ScriptedSend(FakeResponse(200))))
    assert harness.normalizer.freezes == 0


# --- concurrency ---


async def test__per_origin_limiter__bounds_concurrent_sends() -> None:
    config = make_config(retry=None, pool=PoolConfig(max_connections_per_host=1))
    harness = Harness(config)
    active = 0
    peak = 0

    async def send(request: EngineRequest) -> FakeResponse:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        return FakeResponse(200)

    await asyncio.gather(
        harness.engine.run(EngineRequest(), send),
        harness.engine.run(EngineRequest(), send),
    )
    assert peak == 1  # POOL_LIMIT_PER_HOST is EMULATED: the engine serialized the origin


# --- connection metrics ---


async def test__conn_metrics__land_on_the_attempt_and_the_call_span() -> None:
    tracer = RecordingTracer()
    conn = ConnMetrics(dns=0.01, connect=0.02, pool_wait=0.003, reused=False, http_version="1.1")
    harness = Harness(make_config(), tracer=tracer, conn=conn)
    await harness.engine.run(EngineRequest(), as_async_send(ScriptedSend(FakeResponse(200))))
    attributes = tracer.spans[0].attributes
    assert attributes["http.connection.dns_duration"] == 0.01
    assert attributes["http.connection.connect_duration"] == 0.02
    assert attributes["http.connection.pool_wait_duration"] == 0.003
    assert attributes["http.connection.reused"] is False
    assert attributes["network.protocol.version"] == "1.1"
    assert "http.connection.tls_duration" not in attributes  # unset fields stay off the span


async def test__failed_attempt_without_response__no_conn_lookup() -> None:
    tracer = RecordingTracer()
    harness = Harness(make_config(retry=None), tracer=tracer, conn=ConnMetrics(dns=0.5))
    with pytest.raises(ConnectionError):
        await harness.engine.run(EngineRequest(), as_async_send(ScriptedSend(ConnectionError("down"))))
    assert "http.connection.dns_duration" not in tracer.spans[0].attributes
