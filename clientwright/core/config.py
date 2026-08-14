"""Universal, transport-free client configuration.

Three rules keep this config honest:

1. ``UNSET`` is not "disabled": an unset knob defers to the adapter's native
   default and the deferral is visible in the ``ConfigApplicationReport``.
2. No transport types appear here, so the same config is readable by any adapter.
3. Anything set but inexpressible on the chosen adapter lands in
   ``report.dropped``; under ``UnsupportedPolicy.STRICT`` that fails the build.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from .model import IDEMPOTENT_METHODS, CircuitKey, FailureKind


class _Unset:
    """Singleton sentinel distinguishing "user set this" from "default applies"."""

    __slots__ = ()
    _instance: _Unset | None = None

    def __new__(cls) -> _Unset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = _Unset()

type Maybe[T] = T | _Unset


def is_set(value: object) -> bool:
    """True when the value was explicitly provided (is not the UNSET sentinel)."""
    return not isinstance(value, _Unset)


def resolve[T](value: Maybe[T], fallback: T) -> T:
    """Collapse a Maybe to a concrete value."""
    if isinstance(value, _Unset):
        return fallback
    return value


class UnsupportedPolicy(StrEnum):
    IGNORE = "ignore"
    WARN = "warn"
    STRICT = "strict"


class RedirectMode(StrEnum):
    OWNED = "owned"
    NATIVE = "native"


class CallerOverride(StrEnum):
    CALLER_WINS = "caller_wins"
    CONFIG_WINS = "config_wins"
    RAISE = "raise"


class RetryMode(StrEnum):
    OWNED = "owned"
    DELEGATED = "delegated"


DEFAULT_RETRYABLE_KINDS: Final = frozenset(
    {
        FailureKind.CONNECT_TIMEOUT,
        FailureKind.CONNECT_ERROR,
        FailureKind.DNS_ERROR,
        FailureKind.POOL_TIMEOUT,
        FailureKind.READ_TIMEOUT,
        FailureKind.DISCONNECTED,
    }
)

DEFAULT_RETRYABLE_STATUS: Final = frozenset({429, 502, 503, 504})

DEFAULT_TRIP_KINDS: Final = frozenset(
    {
        FailureKind.CONNECT_TIMEOUT,
        FailureKind.READ_TIMEOUT,
        FailureKind.WRITE_TIMEOUT,
        FailureKind.POOL_TIMEOUT,
        FailureKind.TOTAL_TIMEOUT,
        FailureKind.CONNECT_ERROR,
        FailureKind.DNS_ERROR,
        FailureKind.TLS_ERROR,
        FailureKind.DISCONNECTED,
        FailureKind.PROTOCOL_ERROR,
        FailureKind.STATUS,
    }
)

DEFAULT_SENSITIVE_HEADERS: Final = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "api-key",
    }
)

DEFAULT_SENSITIVE_QUERY_PARAMS: Final = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "client_secret",
        "code",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)


def _require_positive(name: str, value: object) -> None:
    if isinstance(value, _Unset) or value is None:
        return
    if isinstance(value, (int, float)) and value <= 0:
        raise ValueError(f"{name} must be positive, got {value!r}")


def _coerce_enum[EnumT: StrEnum](config: object, field: str, enum: type[EnumT]) -> None:
    """Turn a plain string into the real enum member, in place.

    These fields are ``StrEnum``, so ``"delegated"`` looks like it works - but
    the engine compares members with ``is``, and a bare string is never the same
    object as a member. Config loaded from YAML or the environment would then
    match no branch at all and silently take the fallback. Coercing here also
    turns a typo into a ValueError at construction instead of a knob that
    quietly does nothing.
    """
    value = getattr(config, field)
    if type(value) is enum:
        return
    try:
        member = enum(value)
    except ValueError:
        allowed = ", ".join(repr(member.value) for member in enum)
        raise ValueError(f"{field} must be one of {allowed}, got {value!r}") from None
    object.__setattr__(config, field, member)  # frozen dataclass


@dataclass(frozen=True, slots=True)
class TimeoutConfig:
    """Timeout budget of a logical call.

    ``total`` is guaranteed everywhere: the engine enforces it with a monotonic
    deadline shared by all attempts, backoff sleeps and redirect hops.
    Phase knobs left ``UNSET`` defer to the adapter's native defaults.
    """

    total: float | None = 30.0
    attempt: Maybe[float | None] = UNSET
    connect: Maybe[float | None] = 5.0
    read: Maybe[float | None] = UNSET
    write: Maybe[float | None] = UNSET
    pool_acquire: Maybe[float | None] = UNSET

    def __post_init__(self) -> None:
        for name in ("total", "attempt", "connect", "read", "write", "pool_acquire"):
            _require_positive(f"timeout.{name}", getattr(self, name))


@dataclass(frozen=True, slots=True)
class PoolConfig:
    """Connection pool shape; unset knobs defer to native defaults."""

    max_connections: Maybe[int | None] = 100
    max_keepalive: Maybe[int | None] = 20
    keepalive_expiry: Maybe[float | None] = 30.0
    max_connections_per_host: Maybe[int | None] = UNSET
    http2: Maybe[bool] = UNSET

    def __post_init__(self) -> None:
        for name in ("max_connections", "max_keepalive", "keepalive_expiry", "max_connections_per_host"):
            _require_positive(f"pool.{name}", getattr(self, name))


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Owned retry policy; the engine runs the loop, adapters only send."""

    max_attempts: int = 3
    initial_backoff: float = 0.1
    max_backoff: float = 10.0
    multiplier: float = 2.0
    jitter: float = 0.2
    retryable_kinds: frozenset[FailureKind] = DEFAULT_RETRYABLE_KINDS
    retryable_status: frozenset[int] = DEFAULT_RETRYABLE_STATUS
    methods: frozenset[str] = IDEMPOTENT_METHODS
    respect_retry_after: bool = True
    retry_after_max: float = 60.0
    budget_ratio: float | None = 0.1
    require_replayable_body: bool = True
    mode: RetryMode = RetryMode.OWNED

    def __post_init__(self) -> None:
        _coerce_enum(self, "mode", RetryMode)
        if self.max_attempts < 1:
            raise ValueError(f"retry.max_attempts must be >= 1, got {self.max_attempts}")
        _require_positive("retry.initial_backoff", self.initial_backoff)
        _require_positive("retry.max_backoff", self.max_backoff)
        if self.multiplier < 1.0:
            raise ValueError(f"retry.multiplier must be >= 1, got {self.multiplier}")
        if not 0.0 <= self.jitter <= 1.0:
            raise ValueError(f"retry.jitter must be within [0, 1], got {self.jitter}")
        if self.budget_ratio is not None and not 0.0 < self.budget_ratio <= 1.0:
            raise ValueError(f"retry.budget_ratio must be within (0, 1], got {self.budget_ratio}")


@dataclass(frozen=True, slots=True)
class CircuitBreakerConfig:
    """Circuit breaker keyed per CircuitKey; one signal per logical call.

    A ``STATUS`` outcome trips the breaker only for 5xx responses.
    """

    fail_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max_calls: int = 1
    max_keys: int = 512
    key: CircuitKey = CircuitKey.ORIGIN
    trip_kinds: frozenset[FailureKind] = DEFAULT_TRIP_KINDS

    def __post_init__(self) -> None:
        _coerce_enum(self, "key", CircuitKey)
        if self.fail_threshold < 1:
            raise ValueError(f"circuit_breaker.fail_threshold must be >= 1, got {self.fail_threshold}")
        _require_positive("circuit_breaker.recovery_timeout", self.recovery_timeout)
        if self.half_open_max_calls < 1:
            raise ValueError(f"circuit_breaker.half_open_max_calls must be >= 1, got {self.half_open_max_calls}")
        if self.max_keys < 1:
            raise ValueError(f"circuit_breaker.max_keys must be >= 1, got {self.max_keys}")


# Module attribute captured before the dataclass: the field named ``logging``
# shadows the module inside the class body.
_INFO_LEVEL: Final = logging.INFO


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    """Which telemetry channels are active; only knobs that actually work exist here."""

    logging: bool = True
    metrics: bool = True
    tracing: bool = True
    success_log_level: int = _INFO_LEVEL
    sensitive_headers: frozenset[str] = DEFAULT_SENSITIVE_HEADERS
    sensitive_query_params: frozenset[str] = DEFAULT_SENSITIVE_QUERY_PARAMS


@dataclass(frozen=True, slots=True)
class TlsConfig:
    verify: bool = True
    ca_bundle: str | None = None
    cert: str | tuple[str, str] | tuple[str, str, str] | None = None


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    """Explicit proxy or environment-driven proxies (mutually exclusive)."""

    url: str | None = None
    from_env: bool = False

    def __post_init__(self) -> None:
        if self.url is not None and self.from_env:
            raise ValueError("proxy.url and proxy.from_env are mutually exclusive")


@dataclass(frozen=True, slots=True)
class NativeOptions:
    """Raw passthrough to the native client, grouped by adapter-declared slots.

    Validated at build time: unknown slots, reserved keys, typos and collisions
    with explicitly set config fields are all errors, not silent behavior.
    """

    slots: Mapping[str, Mapping[str, object]] = field(default_factory=dict)

    @classmethod
    def of(cls, **slots: Mapping[str, object]) -> NativeOptions:
        return cls(slots={name: dict(values) for name, values in slots.items()})

    def for_slot(self, name: str) -> dict[str, object]:
        return dict(self.slots.get(name, {}))


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """The whole client, described once, readable by every adapter."""

    service_name: str
    base_url: str | None = None
    timeout: TimeoutConfig = field(default_factory=TimeoutConfig)
    pool: PoolConfig = field(default_factory=PoolConfig)
    retry: RetryConfig | None = field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig | None = field(default_factory=CircuitBreakerConfig)
    tls: TlsConfig = field(default_factory=TlsConfig)
    proxy: ProxyConfig | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    redirects: RedirectMode = RedirectMode.OWNED
    max_redirects: int = 5
    caller_override: CallerOverride = CallerOverride.CALLER_WINS
    deadline_header: str | None = None
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    native: NativeOptions = field(default_factory=NativeOptions)
    on_unsupported: UnsupportedPolicy = UnsupportedPolicy.WARN

    def __post_init__(self) -> None:
        _coerce_enum(self, "redirects", RedirectMode)
        _coerce_enum(self, "caller_override", CallerOverride)
        _coerce_enum(self, "on_unsupported", UnsupportedPolicy)
        if not self.service_name or not self.service_name.strip():
            raise ValueError("service_name must be a non-empty string")
        if self.base_url is not None and not self.base_url.startswith(("http://", "https://")):
            raise ValueError(f"base_url must start with http:// or https://, got {self.base_url!r}")
        if self.max_redirects < 0:
            raise ValueError(f"max_redirects must be >= 0, got {self.max_redirects}")


__all__ = [
    "DEFAULT_RETRYABLE_KINDS",
    "DEFAULT_RETRYABLE_STATUS",
    "DEFAULT_SENSITIVE_HEADERS",
    "DEFAULT_SENSITIVE_QUERY_PARAMS",
    "DEFAULT_TRIP_KINDS",
    "UNSET",
    "CallerOverride",
    "CircuitBreakerConfig",
    "ClientConfig",
    "Maybe",
    "NativeOptions",
    "ObservabilityConfig",
    "PoolConfig",
    "ProxyConfig",
    "RedirectMode",
    "RetryConfig",
    "RetryMode",
    "TimeoutConfig",
    "TlsConfig",
    "UnsupportedPolicy",
    "is_set",
    "resolve",
]
