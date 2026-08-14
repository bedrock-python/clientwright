"""aiohttp capability declaration. Zero-dependency: never imports aiohttp."""

from __future__ import annotations

from ...core.capabilities import (
    AdapterCapabilities,
    Capability,
    DurationBoundary,
    SeamGranularity,
    Support,
)
from ...core.model import FailureKind

CAPABILITIES = AdapterCapabilities(
    adapter="aiohttp",
    seam="middleware",
    granularity=SeamGranularity.HOP,
    boundary=DurationBoundary.HEADERS,
    support={
        Capability.TIMEOUT_TOTAL: Support.EMULATED,
        Capability.TIMEOUT_ATTEMPT: Support.EMULATED,
        Capability.TIMEOUT_CONNECT: Support.NATIVE,
        Capability.TIMEOUT_READ: Support.NATIVE,
        Capability.TIMEOUT_WRITE: Support.ABSENT,
        Capability.TIMEOUT_POOL: Support.ABSENT,
        Capability.DEADLINE_HARD: Support.EMULATED,
        Capability.POOL_LIMIT_TOTAL: Support.NATIVE,
        Capability.POOL_LIMIT_PER_HOST: Support.NATIVE,
        Capability.KEEPALIVE: Support.NATIVE,
        Capability.POOL_METRICS: Support.NATIVE,
        Capability.CONN_METRICS: Support.NATIVE,
        Capability.REDIRECTS_OWNABLE: Support.NATIVE,
        Capability.NATIVE_RETRY_DISABLEABLE: Support.DEGRADED,
        Capability.PER_CALL_OPTIONS: Support.EMULATED,
        Capability.RETROFIT: Support.ABSENT,
        Capability.EXACT_NATIVE_TYPE: Support.NATIVE,
        Capability.BALANCER: Support.ABSENT,
        Capability.HTTP2: Support.ABSENT,
        Capability.HTTP3: Support.ABSENT,
        Capability.PROXY: Support.EMULATED,
    },
    emits=frozenset(
        {
            FailureKind.CONNECT_TIMEOUT,
            FailureKind.READ_TIMEOUT,
            FailureKind.TOTAL_TIMEOUT,
            FailureKind.CONNECT_ERROR,
            FailureKind.DNS_ERROR,
            FailureKind.TLS_ERROR,
            FailureKind.PROTOCOL_ERROR,
            FailureKind.DISCONNECTED,
            FailureKind.STATUS,
            FailureKind.CANCELLED,
            FailureKind.CIRCUIT_OPEN,
            FailureKind.UNKNOWN,
        }
    ),
    collapses={
        FailureKind.POOL_TIMEOUT: FailureKind.CONNECT_TIMEOUT,
        FailureKind.WRITE_TIMEOUT: FailureKind.TOTAL_TIMEOUT,
    },
    notes={
        "async_only": "aiohttp has no sync client; build_sync raises. The session must be built inside a running loop.",
        "timeout_write": "aiohttp has no write timeout; a slow upload is bounded only by the attempt ceiling.",
        "timeout_pool": "Pool waiting is folded into the connect phase; on_connection_queued metrics expose it.",
        "per_call_options": "No request extensions; route/idempotency travel via the call_options() context manager.",
        "native_retry": (
            "aiohttp's one-shot idempotent retry on a dropped keep-alive connection is silenced via the private "
            "_retry_connection attribute; DEGRADED because the seam is not a public API."
        ),
        "seam_bypass": (
            "Per-request middlewares=() REPLACES session middlewares and bypasses the engine entirely; TraceConfig "
            "cannot be overridden per request and emits the uninstrumented_calls sentinel when that happens."
        ),
        "ceil_threshold": "ClientTimeout.ceil_threshold is raised so aiohttp never ceils deadlines to whole seconds.",
        "body_duration": "The middleware returns at headers; body read is not instrumented (no body_duration metric).",
        "max_keepalive": "aiohttp has no cap on the NUMBER of keep-alive connections; pool.max_keepalive is ignored.",
    },
)

__all__ = ["CAPABILITIES"]
