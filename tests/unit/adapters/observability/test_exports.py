"""The public import path of the observability backends."""

from __future__ import annotations

import pytest

pytest.importorskip("prometheus_client", reason="requires the [metrics] extra")
pytest.importorskip("opentelemetry", reason="requires the [tracing] extra")

import clientwright.adapters.observability as observability
from clientwright.adapters.observability import OpenTelemetryTracer, PrometheusClientMetrics
from clientwright.adapters.observability._metrics.prometheus import (
    PrometheusClientMetrics as PrivatePrometheus,
)
from clientwright.adapters.observability._tracing.otel import (
    OpenTelemetryTracer as PrivateTracer,
)


def test__package_root__exposes_the_real_backend_classes() -> None:
    assert PrometheusClientMetrics is PrivatePrometheus
    assert OpenTelemetryTracer is PrivateTracer
    assert set(observability.__all__) == {"OpenTelemetryTracer", "PrometheusClientMetrics"}


def test__unknown_attribute__raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="no attribute 'nope'"):
        observability.nope  # noqa: B018 - attribute access IS the assertion
