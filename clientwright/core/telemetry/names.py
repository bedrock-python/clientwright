"""FROZEN metric names and label sets - a wire contract with dashboards.

Changing anything here is a breaking change of the observability contract and
requires a dashboard migration plan; see docs/advanced/migration.md for the
mapping principles from legacy ``rest_client_*``-style names.
"""

from __future__ import annotations

from typing import Final

REQUESTS_TOTAL: Final = "http_client_requests_total"
REQUEST_DURATION: Final = "http_client_request_duration_seconds"
BODY_DURATION: Final = "http_client_body_duration_seconds"
ATTEMPTS_TOTAL: Final = "http_client_attempts_total"
ATTEMPT_DURATION: Final = "http_client_attempt_duration_seconds"
INFLIGHT: Final = "http_client_inflight"
CIRCUIT_STATE: Final = "http_client_circuit_state"
REDIRECT_HOPS_TOTAL: Final = "http_client_redirect_hops_total"
RETRY_SKIPPED_TOTAL: Final = "http_client_retry_skipped_total"
UNINSTRUMENTED_CALLS_TOTAL: Final = "http_client_uninstrumented_calls_total"

LABELS_CALL: Final = ("service", "adapter", "seam", "method", "origin", "route", "status", "outcome")
LABELS_DURATION: Final = ("service", "adapter", "seam", "method", "origin", "route")
LABELS_ATTEMPT: Final = ("service", "adapter", "seam", "method", "origin", "outcome")
LABELS_INFLIGHT: Final = ("service", "adapter", "seam", "origin")
LABELS_CIRCUIT: Final = ("service", "adapter", "key")
LABELS_SEAM: Final = ("service", "adapter", "seam")
LABELS_RETRY_SKIPPED: Final = ("service", "adapter", "seam", "reason")

OUTCOME_SUCCESS: Final = "success"
STATUS_NONE: Final = "none"
ROUTE_UNKNOWN: Final = "unknown"

# Inherited verbatim from service-observability's DEFAULT_REST_BUCKETS: tuned
# for REST latencies and already burned into existing dashboards.
DEFAULT_BUCKETS: Final = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

__all__ = [
    "ATTEMPTS_TOTAL",
    "ATTEMPT_DURATION",
    "BODY_DURATION",
    "CIRCUIT_STATE",
    "DEFAULT_BUCKETS",
    "INFLIGHT",
    "LABELS_ATTEMPT",
    "LABELS_CALL",
    "LABELS_CIRCUIT",
    "LABELS_DURATION",
    "LABELS_INFLIGHT",
    "LABELS_RETRY_SKIPPED",
    "LABELS_SEAM",
    "OUTCOME_SUCCESS",
    "REDIRECT_HOPS_TOTAL",
    "REQUESTS_TOTAL",
    "REQUEST_DURATION",
    "RETRY_SKIPPED_TOTAL",
    "ROUTE_UNKNOWN",
    "STATUS_NONE",
    "UNINSTRUMENTED_CALLS_TOTAL",
]
