"""Transport-neutral data model shared by engines, policies and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}

# Methods whose semantics make a repeat safe without an idempotency key (RFC 9110).
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"})


class FailureKind(StrEnum):
    """Shared alphabet of call outcomes.

    An alphabet, not a shared partition: each adapter declares which kinds it
    can actually emit (``AdapterCapabilities.emits``) and which finer kinds
    collapse into coarser ones (``AdapterCapabilities.collapses``).
    """

    CONNECT_TIMEOUT = "connect_timeout"
    READ_TIMEOUT = "read_timeout"
    WRITE_TIMEOUT = "write_timeout"
    POOL_TIMEOUT = "pool_timeout"
    TOTAL_TIMEOUT = "total_timeout"
    CONNECT_ERROR = "connect_error"
    DNS_ERROR = "dns_error"
    TLS_ERROR = "tls_error"
    PROTOCOL_ERROR = "protocol_error"
    DISCONNECTED = "disconnected"
    BODY_ERROR = "body_error"
    STATUS = "status"
    CANCELLED = "cancelled"
    CIRCUIT_OPEN = "circuit_open"
    UNKNOWN = "unknown"


class CircuitKey(StrEnum):
    """Granularity of the circuit-breaker key."""

    ORIGIN = "origin"
    ORIGIN_ROUTE = "origin_route"
    ORIGIN_METHOD = "origin_method"


@dataclass(frozen=True, slots=True)
class Outcome:
    """Result of a single attempt. ``kind is None`` means success."""

    kind: FailureKind | None
    status_code: int | None = None
    retry_after: float | None = None
    exception: BaseException | None = None

    @property
    def ok(self) -> bool:
        return self.kind is None


@dataclass(frozen=True, slots=True)
class ResolvedTimeouts:
    """Per-attempt timeout plan handed to the adapter before each send.

    ``attempt`` is the hard ceiling of the whole attempt; async engines enforce
    it with task cancellation, sync engines can only clamp the phases below.
    """

    connect: float | None = None
    read: float | None = None
    write: float | None = None
    pool_acquire: float | None = None
    attempt: float | None = None


@dataclass(frozen=True, slots=True)
class ConnMetrics:
    """Optional per-connection timings; ``None`` fields mean the adapter cannot see them."""

    dns: float | None = None
    connect: float | None = None
    tls: float | None = None
    pool_wait: float | None = None
    reused: bool | None = None
    http_version: str | None = None


@dataclass(frozen=True, slots=True)
class Attempt:
    """One physical attempt inside a logical call."""

    index: int
    started: float
    duration: float
    outcome: Outcome
    hop: int = 0
    conn: ConnMetrics | None = None


@dataclass(frozen=True, slots=True)
class RequestInfo:
    """Low-cardinality identity of a logical call."""

    method: str
    origin: str
    url: str
    route: str | None = None
    idempotent: bool = True

    def circuit_key(self, mode: CircuitKey) -> str:
        if mode is CircuitKey.ORIGIN_ROUTE:
            return f"{self.origin} {self.route or 'unknown'}"
        if mode is CircuitKey.ORIGIN_METHOD:
            return f"{self.origin} {self.method}"
        return self.origin


def origin_of(url: str) -> str:
    """Normalize a URL to its origin: ``scheme://host:port`` lowercased, default ports explicit."""
    parts = urlsplit(url)
    scheme = (parts.scheme or "http").lower()
    host = (parts.hostname or "").lower()
    port = parts.port if parts.port is not None else _DEFAULT_PORTS.get(scheme)
    return f"{scheme}://{host}:{port}" if port is not None else f"{scheme}://{host}"


__all__ = [
    "IDEMPOTENT_METHODS",
    "Attempt",
    "CircuitKey",
    "ConnMetrics",
    "FailureKind",
    "Outcome",
    "RequestInfo",
    "ResolvedTimeouts",
    "origin_of",
]
