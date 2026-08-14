"""urllib3 capability declaration. Zero-dependency: never imports urllib3."""

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
    adapter="urllib3",
    seam="urlopen",
    granularity=SeamGranularity.LOGICAL,
    boundary=DurationBoundary.HEADERS,
    support={
        Capability.TIMEOUT_TOTAL: Support.EMULATED,
        Capability.TIMEOUT_ATTEMPT: Support.ABSENT,
        Capability.TIMEOUT_CONNECT: Support.NATIVE,
        Capability.TIMEOUT_READ: Support.NATIVE,
        Capability.TIMEOUT_WRITE: Support.ABSENT,
        Capability.TIMEOUT_POOL: Support.NATIVE,
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
            FailureKind.POOL_TIMEOUT,
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
        FailureKind.PROTOCOL_ERROR: FailureKind.DISCONNECTED,
        FailureKind.WRITE_TIMEOUT: FailureKind.TOTAL_TIMEOUT,
    },
    notes={
        "sync_only": "urllib3 has no async client; build_async raises.",
        "seam": (
            "The engine is injected as an INSTANCE urlopen on a genuine PoolManager (type(client) is "
            "urllib3.PoolManager); recursive native redirect hops re-enter it and pass straight through."
        ),
        "delegated_retries": (
            "RetryMode.DELEGATED is the documented carve-out here: RetryConfig is translated into "
            "urllib3.util.Retry and the native machinery runs the loop below the seam. Per-attempt metrics are "
            "honestly absent (attempts live inside conn.urlopen); observe them via response.retries.history. "
            "The backoff multiplier is fixed at 2 by urllib3; RetryConfig.multiplier is not translated."
        ),
        "timeout_pool": (
            "The only adapter where the pool timeout is real: pool_timeout is injected per call when "
            "max_connections_per_host makes the pool blocking."
        ),
        "pool_limits": "num_pools is an LRU cache of host pools, not a global cap; maxsize+block cap per host.",
        "keepalive": "Connections are kept alive by pool defaults; expiry and keep-alive count are not controllable.",
        "per_call_options": "No request object; route/idempotency travel via the call_options() context manager.",
        "base_url": "urllib3 has no base_url; the build rejects a config that sets one.",
        "proxy": "An explicit proxy builds a genuine urllib3.ProxyManager; env proxies are not read (dropped).",
    },
)

__all__ = ["CAPABILITIES"]
