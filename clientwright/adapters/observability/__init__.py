"""Observability backends behind extras; the core records via protocols only.

Attribute access is lazy so this package imports cleanly with no extras
installed; touching a backend without its extra raises the backend's own
install-hint ImportError.
"""

from typing import TYPE_CHECKING, Any

from .._lazy import lazy_attribute

if TYPE_CHECKING:
    from ._metrics.prometheus import PrometheusClientMetrics as PrometheusClientMetrics
    from ._tracing.otel import OpenTelemetryTracer as OpenTelemetryTracer

_EXPORTS = {
    "OpenTelemetryTracer": "_tracing.otel",
    "PrometheusClientMetrics": "_metrics.prometheus",
}


def __getattr__(name: str) -> Any:
    return lazy_attribute(__name__, globals(), _EXPORTS, name)


__all__ = ["OpenTelemetryTracer", "PrometheusClientMetrics"]
