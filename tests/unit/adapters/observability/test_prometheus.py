"""Prometheus sink: frozen names, labels, singleton semantics."""

from __future__ import annotations

import pytest

prometheus_client = pytest.importorskip("prometheus_client", reason="requires the [metrics] extra")

from prometheus_client import CollectorRegistry  # noqa: E402

from clientwright.adapters.observability._metrics.prometheus import PrometheusClientMetrics  # noqa: E402
from clientwright.core.telemetry import names  # noqa: E402


def _sample_names(registry: CollectorRegistry) -> set[str]:
    return {metric.name for metric in registry.collect()}


def test__all_frozen_families__registered() -> None:
    registry = CollectorRegistry()
    PrometheusClientMetrics(registry=registry)
    collected = _sample_names(registry)
    assert names.REQUEST_DURATION in collected
    assert names.INFLIGHT in collected
    assert names.CIRCUIT_STATE in collected


def test__records__produce_samples_with_frozen_labels() -> None:
    registry = CollectorRegistry()
    sink = PrometheusClientMetrics(registry=registry)
    sink.record_call(
        service="svc",
        adapter="httpx",
        seam="transport",
        method="GET",
        origin="https://a:443",
        route="/u",
        status="200",
        outcome="success",
        duration=0.1,
    )
    sink.record_attempt(
        service="svc",
        adapter="httpx",
        seam="transport",
        method="GET",
        origin="https://a:443",
        outcome="success",
        duration=0.1,
    )
    sink.inflight_delta(service="svc", adapter="httpx", seam="transport", origin="https://a:443", delta=1)
    sink.inflight_delta(service="svc", adapter="httpx", seam="transport", origin="https://a:443", delta=-1)
    sink.record_circuit_state(service="svc", adapter="httpx", key="https://a:443", state="open")
    sink.record_redirect_hop(service="svc", adapter="httpx", seam="transport")
    sink.record_retry_skipped(service="svc", adapter="httpx", seam="transport", reason="budget")
    sink.record_uninstrumented_call(service="svc", adapter="httpx", seam="transport")
    value = registry.get_sample_value(
        names.REQUESTS_TOTAL,
        {
            "service": "svc",
            "adapter": "httpx",
            "seam": "transport",
            "method": "GET",
            "origin": "https://a:443",
            "route": "/u",
            "status": "200",
            "outcome": "success",
        },
    )
    assert value == 1.0
    state = registry.get_sample_value(
        names.CIRCUIT_STATE, {"service": "svc", "adapter": "httpx", "key": "https://a:443"}
    )
    assert state == 2.0
    inflight = registry.get_sample_value(
        names.INFLIGHT,
        {"service": "svc", "adapter": "httpx", "seam": "transport", "origin": "https://a:443"},
    )
    assert inflight == 0.0


def test__body_duration__observed_with_frozen_labels() -> None:
    registry = CollectorRegistry()
    sink = PrometheusClientMetrics(registry=registry)
    sink.record_body_duration(
        service="svc",
        adapter="httpx",
        seam="transport",
        method="GET",
        origin="https://a:443",
        route="/u",
        duration=0.05,
    )
    count = registry.get_sample_value(
        f"{names.BODY_DURATION}_count",
        {
            "service": "svc",
            "adapter": "httpx",
            "seam": "transport",
            "method": "GET",
            "origin": "https://a:443",
            "route": "/u",
        },
    )
    assert count == 1.0


def test__same_prefix_and_registry__same_instance() -> None:
    registry = CollectorRegistry()
    first = PrometheusClientMetrics(prefix="app", registry=registry)
    second = PrometheusClientMetrics(prefix="app", registry=registry)
    assert first is second


def test__prefix__prepended_to_names() -> None:
    registry = CollectorRegistry()
    PrometheusClientMetrics(prefix="app", registry=registry)
    assert f"app_{names.REQUEST_DURATION}" in _sample_names(registry)


def test__invalid_prefix__rejected() -> None:
    with pytest.raises(ValueError, match="Invalid metric prefix"):
        PrometheusClientMetrics(prefix="9bad-prefix", registry=CollectorRegistry())
