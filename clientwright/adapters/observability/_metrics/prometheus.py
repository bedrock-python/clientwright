"""Prometheus backend for the frozen ``http_client_*`` metric families.

Instances are cached per (prefix, registry): repeated construction returns the
same object instead of raising Prometheus duplicate-registration errors - the
same guarantee the legacy ``MetricsMeta`` singleton gave.
"""

from __future__ import annotations

import re
import threading
import weakref
from typing import Any

try:
    from prometheus_client import REGISTRY, Counter, Gauge, Histogram
    from prometheus_client.registry import CollectorRegistry
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError("Prometheus metrics require clientwright[metrics]; install it.") from exc

from ....core.telemetry import names

_PREFIX_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Keyed by the registry OBJECT (weakly): id() of a dead registry can be
# recycled, which would hand back a sink bound to the wrong registry.
_INSTANCES: weakref.WeakKeyDictionary[CollectorRegistry, dict[str | None, PrometheusClientMetrics]] = (
    weakref.WeakKeyDictionary()
)
_INSTANCES_LOCK = threading.Lock()


def _metric_name(name: str, prefix: str | None) -> str:
    if prefix is None:
        return name
    if not _PREFIX_PATTERN.match(prefix):
        raise ValueError(f"Invalid metric prefix {prefix!r}: must match {_PREFIX_PATTERN.pattern}")
    return f"{prefix}_{name}"


class PrometheusClientMetrics:
    """ClientMetricsProtocol backend over prometheus-client."""

    def __new__(
        cls,
        prefix: str | None = None,
        registry: CollectorRegistry = REGISTRY,
        buckets: tuple[float, ...] = names.DEFAULT_BUCKETS,
    ) -> PrometheusClientMetrics:
        with _INSTANCES_LOCK:
            per_registry = _INSTANCES.get(registry)
            if per_registry is None:
                per_registry = {}
                _INSTANCES[registry] = per_registry
            instance = per_registry.get(prefix)
            if instance is None:
                instance = super().__new__(cls)
                instance._init(prefix, registry, buckets)
                per_registry[prefix] = instance
            return instance

    def _init(self, prefix: str | None, registry: CollectorRegistry, buckets: tuple[float, ...]) -> None:
        self._requests_total = Counter(
            _metric_name(names.REQUESTS_TOTAL, prefix),
            "Total number of outbound HTTP client calls",
            names.LABELS_CALL,
            registry=registry,
        )
        self._request_duration = Histogram(
            _metric_name(names.REQUEST_DURATION, prefix),
            "HTTP client call duration in seconds (boundary declared per adapter)",
            names.LABELS_DURATION,
            registry=registry,
            buckets=list(buckets),
        )
        self._body_duration = Histogram(
            _metric_name(names.BODY_DURATION, prefix),
            "HTTP client response body read duration in seconds",
            names.LABELS_DURATION,
            registry=registry,
            buckets=list(buckets),
        )
        self._attempts_total = Counter(
            _metric_name(names.ATTEMPTS_TOTAL, prefix),
            "Total number of physical attempts",
            names.LABELS_ATTEMPT,
            registry=registry,
        )
        self._attempt_duration = Histogram(
            _metric_name(names.ATTEMPT_DURATION, prefix),
            "Physical attempt duration in seconds",
            names.LABELS_ATTEMPT,
            registry=registry,
            buckets=list(buckets),
        )
        self._inflight = Gauge(
            _metric_name(names.INFLIGHT, prefix),
            "Number of in-flight HTTP client calls",
            names.LABELS_INFLIGHT,
            registry=registry,
        )
        self._circuit_state = Gauge(
            _metric_name(names.CIRCUIT_STATE, prefix),
            "Circuit state per key: 0 closed, 1 half-open, 2 open",
            names.LABELS_CIRCUIT,
            registry=registry,
        )
        self._redirect_hops = Counter(
            _metric_name(names.REDIRECT_HOPS_TOTAL, prefix),
            "Redirect hops followed by the engine",
            names.LABELS_SEAM,
            registry=registry,
        )
        self._retry_skipped = Counter(
            _metric_name(names.RETRY_SKIPPED_TOTAL, prefix),
            "Retries the policy wanted but could not perform",
            names.LABELS_RETRY_SKIPPED,
            registry=registry,
        )
        self._uninstrumented = Counter(
            _metric_name(names.UNINSTRUMENTED_CALLS_TOTAL, prefix),
            "Calls that bypassed the instrumentation seam",
            names.LABELS_SEAM,
            registry=registry,
        )

    _STATE_VALUES = {"closed": 0, "half_open": 1, "open": 2}

    def record_call(
        self,
        *,
        service: str,
        adapter: str,
        seam: str,
        method: str,
        origin: str,
        route: str,
        status: str,
        outcome: str,
        duration: float,
    ) -> None:
        self._requests_total.labels(service, adapter, seam, method, origin, route, status, outcome).inc()
        self._request_duration.labels(service, adapter, seam, method, origin, route).observe(duration)

    def record_body_duration(
        self,
        *,
        service: str,
        adapter: str,
        seam: str,
        method: str,
        origin: str,
        route: str,
        duration: float,
    ) -> None:
        self._body_duration.labels(service, adapter, seam, method, origin, route).observe(duration)

    def record_attempt(
        self,
        *,
        service: str,
        adapter: str,
        seam: str,
        method: str,
        origin: str,
        outcome: str,
        duration: float,
    ) -> None:
        self._attempts_total.labels(service, adapter, seam, method, origin, outcome).inc()
        self._attempt_duration.labels(service, adapter, seam, method, origin, outcome).observe(duration)

    def inflight_delta(self, *, service: str, adapter: str, seam: str, origin: str, delta: int) -> None:
        gauge = self._inflight.labels(service, adapter, seam, origin)
        if delta > 0:
            gauge.inc(float(delta))
        elif delta < 0:
            gauge.dec(float(abs(delta)))

    def record_circuit_state(self, *, service: str, adapter: str, key: str, state: str) -> None:
        self._circuit_state.labels(service, adapter, key).set(self._STATE_VALUES.get(state, 0))

    def record_redirect_hop(self, *, service: str, adapter: str, seam: str) -> None:
        self._redirect_hops.labels(service, adapter, seam).inc()

    def record_retry_skipped(self, *, service: str, adapter: str, seam: str, reason: str) -> None:
        self._retry_skipped.labels(service, adapter, seam, reason).inc()

    def record_uninstrumented_call(self, *, service: str, adapter: str, seam: str) -> None:
        self._uninstrumented.labels(service, adapter, seam).inc()


def get_client_metrics(
    prefix: str | None = None,
    registry: Any = REGISTRY,
    buckets: tuple[float, ...] | None = None,
) -> PrometheusClientMetrics:
    return PrometheusClientMetrics(prefix, registry, buckets or names.DEFAULT_BUCKETS)


__all__ = ["PrometheusClientMetrics", "get_client_metrics"]
