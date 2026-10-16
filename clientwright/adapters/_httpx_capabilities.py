"""Capability record of the httpx family: httpx and its successor httpx2.

Kept apart from ``_httpx_shared`` so that ``capabilities_matrix()`` stays light:
the capability modules import this one, which needs only the core's capability
and model types, not the engines, asyncio or ssl that ``_httpx_shared`` loads.
"""

from __future__ import annotations

from ..core.capabilities import (
    AdapterCapabilities,
    Capability,
    DurationBoundary,
    SeamGranularity,
    Support,
)
from ..core.model import FailureKind


def capabilities_for(adapter: str) -> AdapterCapabilities:
    """The family capability record; only the adapter name differs."""
    return AdapterCapabilities(
        adapter=adapter,
        seam="transport",
        granularity=SeamGranularity.HOP,
        boundary=DurationBoundary.HEADERS,
        support={
            Capability.TIMEOUT_TOTAL: Support.EMULATED,
            Capability.TIMEOUT_ATTEMPT: Support.EMULATED,
            Capability.TIMEOUT_CONNECT: Support.NATIVE,
            Capability.TIMEOUT_READ: Support.NATIVE,
            Capability.TIMEOUT_WRITE: Support.NATIVE,
            Capability.TIMEOUT_POOL: Support.NATIVE,
            Capability.DEADLINE_HARD: Support.EMULATED,
            Capability.DEADLINE_COVERS_BODY: Support.EMULATED,
            Capability.POOL_LIMIT_TOTAL: Support.NATIVE,
            Capability.POOL_LIMIT_PER_HOST: Support.EMULATED,
            Capability.KEEPALIVE: Support.NATIVE,
            Capability.POOL_METRICS: Support.ABSENT,
            Capability.CONN_METRICS: Support.ABSENT,
            Capability.REDIRECTS_OWNABLE: Support.NATIVE,
            Capability.NATIVE_RETRY_DISABLEABLE: Support.NATIVE,
            Capability.PER_CALL_OPTIONS: Support.NATIVE,
            Capability.RETROFIT: Support.ABSENT,
            Capability.EXACT_NATIVE_TYPE: Support.NATIVE,
            Capability.BALANCER: Support.ABSENT,
            Capability.HTTP2: Support.NATIVE,
            Capability.HTTP3: Support.ABSENT,
            Capability.PROXY: Support.NATIVE,
        },
        emits=frozenset(
            {
                FailureKind.CONNECT_TIMEOUT,
                FailureKind.READ_TIMEOUT,
                FailureKind.WRITE_TIMEOUT,
                FailureKind.POOL_TIMEOUT,
                FailureKind.ATTEMPT_TIMEOUT,
                FailureKind.TOTAL_TIMEOUT,
                FailureKind.CONNECT_ERROR,
                FailureKind.TLS_ERROR,
                FailureKind.PROTOCOL_ERROR,
                FailureKind.DISCONNECTED,
                FailureKind.BODY_ERROR,
                FailureKind.STATUS,
                FailureKind.CANCELLED,
                FailureKind.CIRCUIT_OPEN,
                FailureKind.UNKNOWN,
            }
        ),
        collapses={FailureKind.DNS_ERROR: FailureKind.CONNECT_ERROR},
        notes={
            "deadline_hard": "Hard cancellation on the async client only; the sync client clamps phases (soft).",
            "attempt_timeout": (
                "Emitted by the async client only; the sync client drops the attempt ceiling, so a stall arrives as "
                "read_timeout."
            ),
            "pool_limit_per_host": "Emulated as a per-origin in-flight semaphore; limits requests, not connections.",
            "dns_error": f"{adapter} wraps DNS failures into ConnectError; they surface as connect_error.",
            "proxy_from_env": "Environment proxies are parsed into mounts; NO_PROXY entries match hosts literally.",
            "deadline_covers_body": (
                "The response body is inside the total: the async client bounds every chunk by the remaining budget, "
                "the sync client refuses the next chunk once the budget is gone (soft)."
            ),
        },
    )


__all__ = ["capabilities_for"]
