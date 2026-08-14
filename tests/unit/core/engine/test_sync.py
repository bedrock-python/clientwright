"""The sync attempt engine end-to-end over fakes: same loop, blocking IO.

The integration suite proves the engine against real clients; this file pins
the loop's decision points deterministically - admission, retries, redirects,
deadlines, aborts and the telemetry that must survive each of them.
"""

from __future__ import annotations

import threading
import time

import pytest

from clientwright.core.config import CircuitBreakerConfig, PoolConfig, RedirectMode
from clientwright.core.contracts.adapter import AdapterDeps
from clientwright.core.errors import CircuitOpenError, DeadlineExceededError
from tests.helpers.engine import (
    EngineRequest,
    FixedDeadlineSource,
    Harness,
    ScriptedSend,
    as_sync_send,
    fast_retry,
    make_config,
    redirect_response,
)
from tests.helpers.views import FakeResponse


def test__success__returns_native_response_and_closes_telemetry() -> None:
    harness = Harness(make_config(), sync=True)
    result = harness.engine.run(EngineRequest(), as_sync_send(ScriptedSend(FakeResponse(200))))
    assert result.status_code == 200
    assert harness.call_outcomes == ["success"]
    assert harness.metrics.inflight_balance == 0
    assert harness.normalizer.wrapped_streams == 1


def test__503_then_200__retries_discards_and_rewinds() -> None:
    harness = Harness(make_config(), sync=True)
    script = ScriptedSend(FakeResponse(503), FakeResponse(200))
    result = harness.engine.run(EngineRequest(), as_sync_send(script))
    assert result.status_code == 200
    assert harness.attempt_outcomes == ["status", "success"]
    assert harness.normalizer.discards == 1
    assert harness.normalizer.rewinds == 1


def test__ambient_budget_pre_expired__raises_before_any_send() -> None:
    deps = AdapterDeps(deadline_source=FixedDeadlineSource(0.0))
    harness = Harness(make_config(), deps=deps, sync=True)
    script = ScriptedSend()
    with pytest.raises(DeadlineExceededError):
        harness.engine.run(EngineRequest(), as_sync_send(script))
    assert script.sent == 0
    assert harness.call_outcomes == ["total_timeout"]


def test__base_exception__aborts_the_breaker_instead_of_failing_it() -> None:
    config = make_config(retry=None, circuit_breaker=CircuitBreakerConfig(fail_threshold=1))
    harness = Harness(config, sync=True)
    with pytest.raises(KeyboardInterrupt):
        harness.engine.run(EngineRequest(), as_sync_send(ScriptedSend(KeyboardInterrupt())))
    assert harness.runtime.circuits is not None
    state = next(iter(harness.runtime.circuits.snapshot().values()))
    assert state.failures == 0


def test__open_circuit__rejects_without_a_send() -> None:
    config = make_config(retry=None, circuit_breaker=CircuitBreakerConfig(fail_threshold=1))
    harness = Harness(config, sync=True)
    with pytest.raises(ConnectionError):
        harness.engine.run(EngineRequest(), as_sync_send(ScriptedSend(ConnectionError("boom"))))
    rejected = ScriptedSend()
    with pytest.raises(CircuitOpenError):
        harness.engine.run(EngineRequest(), as_sync_send(rejected))
    assert rejected.sent == 0


def test__retry_budget_exhausted__returns_response_with_sentinel() -> None:
    harness = Harness(make_config(retry=fast_retry(budget_ratio=0.1)), sync=True)
    budgets = harness.runtime.retry_budgets
    assert budgets is not None
    origin = EngineRequest().info.origin
    budgets.earn(origin)
    while budgets.try_spend(origin):
        pass
    result = harness.engine.run(EngineRequest(), as_sync_send(ScriptedSend(FakeResponse(503))))
    assert result.status_code == 503
    assert harness.skip_reasons == ["budget"]


def test__native_mode__returns_redirect_response_untouched() -> None:
    config = make_config(retry=None, redirects=RedirectMode.NATIVE)
    harness = Harness(config, sync=True)
    request = EngineRequest()
    result = harness.engine.run(request, as_sync_send(ScriptedSend(redirect_response("/next"))))
    assert result.status_code == 302
    assert request.retargets == []


def test__owned_hop__follows_and_strips_cross_origin_credentials() -> None:
    harness = Harness(make_config(), sync=True)
    request = EngineRequest(url="http://a.example/x", headers={"authorization": "secret", "accept": "json"})
    script = ScriptedSend(redirect_response("http://b.example/y"), FakeResponse(200))
    result = harness.engine.run(request, as_sync_send(script))
    assert result.status_code == 200
    _, _, hop_headers = script.calls[1]
    assert "authorization" not in hop_headers
    assert hop_headers["accept"] == "json"


def test__call_error_from_below__classified_not_wrapped() -> None:
    harness = Harness(make_config(retry=None), sync=True)
    with pytest.raises(DeadlineExceededError):
        harness.engine.run(EngineRequest(), as_sync_send(ScriptedSend(DeadlineExceededError(1.0))))
    assert harness.call_outcomes == ["total_timeout"]


def test__per_origin_limiter__bounds_concurrent_sends_across_threads() -> None:
    config = make_config(retry=None, pool=PoolConfig(max_connections_per_host=1))
    harness = Harness(config, sync=True)
    lock = threading.Lock()
    active = 0
    peak = 0

    def send(request: EngineRequest) -> FakeResponse:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return FakeResponse(200)

    threads = [threading.Thread(target=lambda: harness.engine.run(EngineRequest(), send)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak == 1
