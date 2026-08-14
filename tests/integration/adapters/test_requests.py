"""Behavioral conformance of the requests adapter against a real origin.

requests has no base_url, so every call uses absolute URLs; everything else
mirrors the httpx sync suite.
"""

from __future__ import annotations

import pytest

requests = pytest.importorskip("requests", reason="requires the [requests] extra")

import clientwright  # noqa: E402
from clientwright import AdapterDeps, ClientConfig, RetryConfig, TimeoutConfig  # noqa: E402
from clientwright.adapters.requests import (  # noqa: E402
    RequestsCircuitOpenError,
    RequestsTooManyRedirectsError,
    call_options,
)
from clientwright.core.config import CircuitBreakerConfig  # noqa: E402
from clientwright.core.testing import OriginServer, RecordingMetrics  # noqa: E402

FAST_RETRY = RetryConfig(max_attempts=3, initial_backoff=0.01, jitter=0.0)


def config_for(**overrides: object) -> ClientConfig:
    return ClientConfig(service_name="conformance", **overrides)  # type: ignore[arg-type]


def build(config: ClientConfig, deps: AdapterDeps) -> requests.Session:
    client = clientwright.build_sync("requests", config, deps)
    assert type(client) is requests.Session
    return client


# --- basics ---


def test__echo__native_session_and_injected_headers(origin: OriginServer, metrics: RecordingMetrics) -> None:
    deps = AdapterDeps(metrics=metrics, header_providers=(lambda: {"X-Request-ID": "rid-1"},))
    session = build(config_for(headers={"X-Static": "yes"}), deps)
    response = session.get(origin.url + "/echo", headers={"X-Static": "caller-wins"})
    payload = response.json()
    assert payload["headers"]["x-request-id"] == "rid-1"
    assert payload["headers"]["x-static"] == "caller-wins"  # caller headers never overwritten
    session.close()


def test__call_options_route__becomes_metric_label(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    session = build(config_for(), deps)
    with call_options(route="/echo-route"):
        session.get(origin.url + "/echo")
    session.close()
    assert metrics.calls[0]["route"] == "/echo-route"


def test__no_session_timeout_hole__engine_supplies_one(origin: OriginServer, deps: AdapterDeps) -> None:
    # A bare session.get() would hang forever on stock requests; the engine
    # clamps the read phase with the total budget.
    session = build(config_for(timeout=TimeoutConfig(total=0.5, connect=1.0), retry=None), deps)
    with pytest.raises(requests.Timeout):
        session.get(origin.url + "/slow/3")
    session.close()


# --- retries ---


def test__503_then_200__retried_to_success(origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps) -> None:
    session = build(config_for(retry=FAST_RETRY), deps)
    response = session.get(origin.url + "/flaky/rq1/2")
    assert response.status_code == 200
    assert origin.request_count("/flaky/rq1/2") == 3
    assert len(metrics.attempts) == 3
    session.close()


def test__post__not_retried_without_idempotency(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    session = build(config_for(retry=FAST_RETRY), deps)
    response = session.post(origin.url + "/flaky/rq2/1", data=b"data")
    assert response.status_code == 503
    assert origin.request_count("/flaky/rq2/1") == 1
    assert metrics.retry_skips[0]["reason"] == "method"
    session.close()


def test__post_with_idempotent_option__retried_with_body(origin: OriginServer, deps: AdapterDeps) -> None:
    session = build(config_for(retry=FAST_RETRY), deps)
    with call_options(idempotent=True):
        response = session.post(origin.url + "/flaky/rq3/1", data=b"data")
    assert response.status_code == 200
    assert origin.request_count("/flaky/rq3/1") == 2
    session.close()


def test__caller_timeout__wins_over_config(origin: OriginServer, deps: AdapterDeps) -> None:
    session = build(config_for(retry=None), deps)
    with pytest.raises(requests.Timeout):
        session.get(origin.url + "/slow/2", timeout=0.3)
    session.close()


# --- redirects ---


def test__chain__followed_by_engine_with_hop_metric(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    session = build(config_for(), deps)
    response = session.get(origin.url + "/redirect/3")
    assert response.status_code == 200
    assert response.url.endswith("/echo")  # response attributed to the final URL
    assert len(metrics.redirect_hops) == 3
    assert len(metrics.calls) == 1  # one logical call despite hops
    session.close()


def test__loop__raises_dual_family_too_many_redirects(origin: OriginServer, deps: AdapterDeps) -> None:
    session = build(config_for(max_redirects=3), deps)
    with pytest.raises(RequestsTooManyRedirectsError) as excinfo:
        session.get(origin.url + "/redirect-loop")
    assert isinstance(excinfo.value, requests.TooManyRedirects)
    session.close()


def test__post_303__demoted_to_get_with_dropped_body(origin: OriginServer, deps: AdapterDeps) -> None:
    session = build(config_for(), deps)
    response = session.post(origin.url + "/redirect/1", data=b"body")
    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == "GET"
    assert payload["body"] == ""
    session.close()


# --- deadline ---


def test__deadline_header__stamped_with_remaining_budget(origin: OriginServer, deps: AdapterDeps) -> None:
    session = build(config_for(timeout=TimeoutConfig(total=30.0), deadline_header="X-Deadline-Ms"), deps)
    response = session.get(origin.url + "/echo")
    stamped = int(response.json()["headers"]["x-deadline-ms"])
    assert 0 < stamped <= 30_000
    session.close()


# --- circuit breaker ---


def test__threshold__opens_and_rejects_without_touching_origin(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    config = config_for(
        retry=None,
        circuit_breaker=CircuitBreakerConfig(fail_threshold=2, recovery_timeout=60.0),
    )
    session = build(config, deps)
    for _ in range(2):
        assert session.get(origin.url + "/status/503").status_code == 503
    before = origin.request_count("/status/503")
    with pytest.raises(RequestsCircuitOpenError) as excinfo:
        session.get(origin.url + "/status/503")
    assert isinstance(excinfo.value, requests.RequestException)
    assert origin.request_count("/status/503") == before  # rejected locally
    assert metrics.inflight_balance == 0
    session.close()
