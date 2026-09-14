"""Settings models for ``ClientConfig`` (``[settings]`` extra).

One pydantic model per config dataclass - the same field names, the same
defaults - and ``to_config()`` on each, so the translation from an
environment-loaded settings shape to a ``ClientConfig`` is written here, once,
instead of in every service that uses the library.

Every class here is a plain ``BaseModel``, never a ``BaseSettings``: a section
is reachable only through the settings object you nest it in, so a bare
``BASE_URL`` or ``TIMEOUT`` in a pod cannot reach it. The parent - its prefix,
its nesting delimiter, its ``.env`` file - stays yours::

    from pydantic_settings import BaseSettings, SettingsConfigDict

    from clientwright.contrib.settings import BaseClientSettings


    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_nested_delimiter="__")

        warehouse: BaseClientSettings = BaseClientSettings()


    # WAREHOUSE__BASE_URL=https://wh.example.com WAREHOUSE__TIMEOUT__TOTAL=10 WAREHOUSE__POOL__HTTP2=true
    config = Settings().warehouse.to_config("warehouse")

``UNSET`` survives the trip: a knob the config leaves ``UNSET`` by default
(``timeout.read``, ``pool.http2``, ...) reaches the config as ``UNSET`` unless
you set it, and an explicit ``null`` is the dataclass' explicit "unbounded" -
the models tell the two apart with ``model_fields_set``. Two things are not
environment-shaped and are not here: ``service_name`` is the argument of
:meth:`BaseClientSettings.to_config`, and ``observability.url_masker`` is a
callable to set on the config afterwards.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from ..core.config import (
    DEFAULT_RETRYABLE_KINDS,
    DEFAULT_RETRYABLE_STATUS,
    DEFAULT_SENSITIVE_QUERY_PARAMS,
    DEFAULT_TRIP_KINDS,
    UNSET,
    CallerOverride,
    CircuitBreakerConfig,
    ClientConfig,
    NativeOptions,
    ObservabilityConfig,
    PoolConfig,
    ProxyConfig,
    RedirectMode,
    RetryConfig,
    RetryMode,
    TimeoutConfig,
    TlsConfig,
    UnsupportedPolicy,
)
from ..core.model import IDEMPOTENT_METHODS, CircuitKey, FailureKind

try:
    from pydantic import BaseModel, Field, field_validator, model_validator
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError("Settings models require clientwright[settings]; install it.") from exc


def _maybe(model: BaseModel, name: str) -> Any:
    """The field's value if it was given, else UNSET - the adapter's native default."""
    return getattr(model, name) if name in model.model_fields_set else UNSET


class BaseTimeoutSettings(BaseModel):
    """``TimeoutConfig`` as settings.

    A phase you do not set stays ``UNSET`` in the config, exactly as in
    ``TimeoutConfig()``; an explicit ``null`` is the explicit "unbounded".
    """

    total: float | None = Field(
        default=30.0, gt=0, description="Wall clock for the whole logical call; null = unbounded"
    )
    attempt: float | None = Field(default=None, gt=0, description="Ceiling for one attempt")
    connect: float | None = Field(default=5.0, gt=0, description="Connect phase")
    read: float | None = Field(default=None, gt=0, description="Read phase")
    write: float | None = Field(default=None, gt=0, description="Write phase")
    pool_acquire: float | None = Field(default=None, gt=0, description="Wait for a pooled connection")

    def to_config(self) -> TimeoutConfig:
        return TimeoutConfig(
            total=self.total,
            attempt=_maybe(self, "attempt"),
            connect=self.connect,
            read=_maybe(self, "read"),
            write=_maybe(self, "write"),
            pool_acquire=_maybe(self, "pool_acquire"),
        )


class BasePoolSettings(BaseModel):
    """``PoolConfig`` as settings; ``max_connections_per_host`` and ``http2`` stay ``UNSET`` until set."""

    max_connections: int | None = Field(default=100, gt=0, description="Pool-wide connection cap; null = unbounded")
    max_keepalive: int | None = Field(default=20, gt=0, description="Idle connections kept open")
    keepalive_expiry: float | None = Field(default=30.0, gt=0, description="Seconds an idle connection is kept")
    max_connections_per_host: int | None = Field(default=None, gt=0, description="Per-origin connection cap")
    http2: bool | None = Field(default=None, description="HTTP/2 where the adapter can honour it")

    def to_config(self) -> PoolConfig:
        return PoolConfig(
            max_connections=self.max_connections,
            max_keepalive=self.max_keepalive,
            keepalive_expiry=self.keepalive_expiry,
            max_connections_per_host=_maybe(self, "max_connections_per_host"),
            http2=UNSET if self.http2 is None else self.http2,
        )


class BaseRetrySettings(BaseModel):
    """``RetryConfig`` as settings; the sets take JSON lists, ``mode`` its value (``owned`` / ``delegated``)."""

    max_attempts: int = Field(default=3, ge=1, description="Attempts per redirect hop, the first included")
    initial_backoff: float = Field(default=0.1, gt=0, description="First backoff, seconds")
    max_backoff: float = Field(default=10.0, gt=0, description="Backoff ceiling, seconds")
    multiplier: float = Field(default=2.0, ge=1, description="Backoff growth per attempt")
    jitter: float = Field(default=0.2, ge=0, le=1, description="Multiplicative jitter within [0, 1]")
    retryable_kinds: frozenset[FailureKind] = Field(
        default=DEFAULT_RETRYABLE_KINDS, description="Failure kinds worth a retry"
    )
    retryable_status: frozenset[int] = Field(default=DEFAULT_RETRYABLE_STATUS, description="Statuses worth a retry")
    methods: frozenset[str] = Field(default=IDEMPOTENT_METHODS, description="Methods retried without a per-call flag")
    respect_retry_after: bool = Field(default=True, description="A Retry-After header replaces the computed backoff")
    retry_after_max: float = Field(default=60.0, description="Cap on what a server may ask for, seconds")
    budget_ratio: float | None = Field(
        default=0.1, gt=0, le=1, description="Share of an origin's traffic that may be retries; null = no budget"
    )
    require_replayable_body: bool = Field(default=True, description="Refuse to retry a body that cannot be replayed")
    mode: RetryMode = Field(default=RetryMode.OWNED, description="owned by the engine, or delegated (urllib3 only)")

    def to_config(self) -> RetryConfig:
        return RetryConfig(
            max_attempts=self.max_attempts,
            initial_backoff=self.initial_backoff,
            max_backoff=self.max_backoff,
            multiplier=self.multiplier,
            jitter=self.jitter,
            retryable_kinds=self.retryable_kinds,
            retryable_status=self.retryable_status,
            methods=self.methods,
            respect_retry_after=self.respect_retry_after,
            retry_after_max=self.retry_after_max,
            budget_ratio=self.budget_ratio,
            require_replayable_body=self.require_replayable_body,
            mode=self.mode,
        )


class BaseCircuitBreakerSettings(BaseModel):
    """``CircuitBreakerConfig`` as settings; ``key`` by value: ``origin``, ``origin_route``, ``origin_method``."""

    fail_threshold: int = Field(default=5, ge=1, description="Consecutive tripping calls before the circuit opens")
    recovery_timeout: float = Field(default=60.0, gt=0, description="Seconds open before the next call is a probe")
    half_open_max_calls: int = Field(default=1, ge=1, description="Concurrent probes while half-open")
    max_keys: int = Field(default=512, ge=1, description="LRU cap on tracked circuits")
    key: CircuitKey = Field(default=CircuitKey.ORIGIN, description="What one circuit stands for")
    trip_kinds: frozenset[FailureKind] = Field(default=DEFAULT_TRIP_KINDS, description="Failure kinds that count")

    def to_config(self) -> CircuitBreakerConfig:
        return CircuitBreakerConfig(
            fail_threshold=self.fail_threshold,
            recovery_timeout=self.recovery_timeout,
            half_open_max_calls=self.half_open_max_calls,
            max_keys=self.max_keys,
            key=self.key,
            trip_kinds=self.trip_kinds,
        )


class BaseTlsSettings(BaseModel):
    """``TlsConfig`` as settings; ``cert`` is a PEM path, or a JSON list of two or three paths."""

    verify: bool = Field(default=True, description="Verify the server certificate")
    ca_bundle: str | None = Field(default=None, description="Path to a private CA bundle")
    cert: str | tuple[str, str] | tuple[str, str, str] | None = Field(
        default=None, description="Client certificate: a PEM path, (cert, key) or (cert, key, password)"
    )

    def to_config(self) -> TlsConfig:
        return TlsConfig(verify=self.verify, ca_bundle=self.ca_bundle, cert=self.cert)


class BaseProxySettings(BaseModel):
    """``ProxyConfig`` as settings: an explicit URL or the environment's proxies, not both."""

    url: str | None = Field(default=None, description="Explicit proxy URL")
    from_env: bool = Field(default=False, description="Read HTTP(S)_PROXY / NO_PROXY instead")

    @model_validator(mode="after")
    def _exclusive(self) -> BaseProxySettings:
        if self.url is not None and self.from_env:
            raise ValueError("proxy.url and proxy.from_env are mutually exclusive")
        return self

    def to_config(self) -> ProxyConfig:
        return ProxyConfig(url=self.url, from_env=self.from_env)


# Module attribute captured before the class: the field named ``logging``
# shadows the module inside the class body, as in ``ObservabilityConfig``.
_INFO_LEVEL: Final = logging.INFO


class BaseObservabilitySettings(BaseModel):
    """``ObservabilityConfig`` as settings, minus ``url_masker``: a callable belongs on the config.

    ``success_log_level`` takes a level name (``DEBUG``) as well as a number.
    """

    logging: bool = Field(default=True, description="Emit log records")
    metrics: bool = Field(default=True, description="Record metrics")
    tracing: bool = Field(default=True, description="Open spans")
    success_log_level: int = Field(default=_INFO_LEVEL, description="Level of the record for a successful call")
    sensitive_query_params: frozenset[str] = Field(
        default=DEFAULT_SENSITIVE_QUERY_PARAMS, description="Query parameters redacted by name in URLs"
    )

    @field_validator("success_log_level", mode="before")
    @classmethod
    def _level_by_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        level = logging.getLevelNamesMapping().get(value.upper())
        if level is None:
            raise ValueError(f"unknown log level {value!r}")
        return level

    def to_config(self) -> ObservabilityConfig:
        return ObservabilityConfig(
            logging=self.logging,
            metrics=self.metrics,
            tracing=self.tracing,
            success_log_level=self.success_log_level,
            sensitive_query_params=self.sensitive_query_params,
        )


class BaseClientSettings(BaseModel):
    """``ClientConfig`` as settings: the whole client, one section per sub-config.

    Nest it in your own settings object; ``service_name`` is not environment-shaped
    and is the argument of :meth:`to_config`. ``retry`` and ``circuit_breaker``
    are on by default and go off with ``retry: None = None`` in a subclass (or
    ``RETRY=null`` in the environment); ``proxy`` is off until any of its
    fields is set.
    """

    base_url: str | None = Field(
        default=None,
        pattern=r"^https?://",
        description="Origin every relative URL joins; unset means absolute URLs per call, "
        "the only mode the requests and urllib3 adapters support",
    )
    timeout: BaseTimeoutSettings = Field(default_factory=BaseTimeoutSettings)
    pool: BasePoolSettings = Field(default_factory=BasePoolSettings)
    retry: BaseRetrySettings | None = Field(default_factory=BaseRetrySettings)
    circuit_breaker: BaseCircuitBreakerSettings | None = Field(default_factory=BaseCircuitBreakerSettings)
    tls: BaseTlsSettings = Field(default_factory=BaseTlsSettings)
    proxy: BaseProxySettings | None = None
    headers: dict[str, str] = Field(default_factory=dict, description="Headers injected with setdefault semantics")
    redirects: RedirectMode = Field(default=RedirectMode.OWNED, description="owned by the engine, or native")
    max_redirects: int = Field(default=5, ge=0, description="Hops before TooManyRedirectsError")
    caller_override: CallerOverride = Field(
        default=CallerOverride.CALLER_WINS, description="What a per-call timeout does: caller_wins, config_wins, raise"
    )
    deadline_header: str | None = Field(default=None, description="Header stamped with the remaining budget, in ms")
    observability: BaseObservabilitySettings = Field(default_factory=BaseObservabilitySettings)
    native: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Raw passthrough: {slot: {kwarg: value}}"
    )
    on_unsupported: UnsupportedPolicy = Field(
        default=UnsupportedPolicy.WARN, description="What a knob the adapter cannot express does: ignore, warn, strict"
    )

    def to_config(self, service_name: str) -> ClientConfig:
        """The ``ClientConfig`` these settings describe, labelled ``service_name``."""
        return ClientConfig(
            service_name=service_name,
            base_url=self.base_url,
            timeout=self.timeout.to_config(),
            pool=self.pool.to_config(),
            retry=None if self.retry is None else self.retry.to_config(),
            circuit_breaker=None if self.circuit_breaker is None else self.circuit_breaker.to_config(),
            tls=self.tls.to_config(),
            proxy=None if self.proxy is None else self.proxy.to_config(),
            headers=self.headers,
            redirects=self.redirects,
            max_redirects=self.max_redirects,
            caller_override=self.caller_override,
            deadline_header=self.deadline_header,
            observability=self.observability.to_config(),
            native=NativeOptions(slots=self.native),
            on_unsupported=self.on_unsupported,
        )


__all__ = [
    "BaseCircuitBreakerSettings",
    "BaseClientSettings",
    "BaseObservabilitySettings",
    "BasePoolSettings",
    "BaseProxySettings",
    "BaseRetrySettings",
    "BaseTimeoutSettings",
    "BaseTlsSettings",
]
