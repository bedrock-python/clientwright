"""requests capability declaration. Zero-dependency: never imports requests."""

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
    adapter="requests",
    seam="http_adapter",
    granularity=SeamGranularity.HOP,
    boundary=DurationBoundary.HEADERS,
    support={
        Capability.TIMEOUT_TOTAL: Support.EMULATED,
        Capability.TIMEOUT_ATTEMPT: Support.ABSENT,
        Capability.TIMEOUT_CONNECT: Support.NATIVE,
        Capability.TIMEOUT_READ: Support.NATIVE,
        Capability.TIMEOUT_WRITE: Support.ABSENT,
        Capability.TIMEOUT_POOL: Support.ABSENT,
        Capability.DEADLINE_HARD: Support.ABSENT,
        Capability.POOL_LIMIT_TOTAL: Support.ABSENT,
        Capability.POOL_LIMIT_PER_HOST: Support.NATIVE,
        Capability.KEEPALIVE: Support.DEGRADED,
        Capability.POOL_METRICS: Support.ABSENT,
        Capability.CONN_METRICS: Support.ABSENT,
        Capability.REDIRECTS_OWNABLE: Support.NATIVE,
        Capability.NATIVE_RETRY_DISABLEABLE: Support.NATIVE,
        Capability.PER_CALL_OPTIONS: Support.EMULATED,
        Capability.RETROFIT: Support.ABSENT,
        Capability.EXACT_NATIVE_TYPE: Support.NATIVE,
        Capability.BALANCER: Support.ABSENT,
        Capability.HTTP2: Support.ABSENT,
        Capability.HTTP3: Support.ABSENT,
        Capability.PROXY: Support.NATIVE,
    },
    emits=frozenset(
        {
            FailureKind.CONNECT_TIMEOUT,
            FailureKind.READ_TIMEOUT,
            FailureKind.TOTAL_TIMEOUT,
            FailureKind.CONNECT_ERROR,
            FailureKind.DNS_ERROR,
            FailureKind.TLS_ERROR,
            FailureKind.DISCONNECTED,
            FailureKind.BODY_ERROR,
            FailureKind.STATUS,
            FailureKind.CIRCUIT_OPEN,
            FailureKind.UNKNOWN,
        }
    ),
    collapses={
        FailureKind.POOL_TIMEOUT: FailureKind.CONNECT_TIMEOUT,
        FailureKind.PROTOCOL_ERROR: FailureKind.DISCONNECTED,
        FailureKind.WRITE_TIMEOUT: FailureKind.TOTAL_TIMEOUT,
    },
    notes={
        "sync_only": "requests has no async client; build_async raises.",
        "no_session_timeout": (
            "requests has NO session-level timeout default - a bare session.get() hangs forever. The engine "
            "closes that hole: every attempt is sent with the planned (connect, read) tuple."
        ),
        "timeout_pool": "HTTPAdapter.send never forwards pool_timeout; a saturated blocking pool waits inside connect.",
        "pool_limits": (
            "requests pools are per-host (pool_maxsize); there is no global cap - pool_connections is an LRU of "
            "host pools, not a limit."
        ),
        "keepalive": "Connections stay alive per urllib3 defaults; expiry and keep-alive count are not controllable.",
        "base_url": "requests has no base_url; the build rejects a config that sets one.",
        "per_call_options": "No request extensions; route/idempotency travel via the call_options() context manager.",
        "protocol_error": "requests folds protocol violations into ConnectionError; they surface as disconnected.",
    },
)

__all__ = ["CAPABILITIES"]
