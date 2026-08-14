"""Structural settings protocols for service integration.

Services keep their own settings models (pydantic or otherwise); anything with
these read-only properties satisfies the contract - the org convention set by
grpc-client-kit. ``client_config_from_settings`` converts the structural shape
into a ``ClientConfig``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..config import (
    CircuitBreakerConfig,
    ClientConfig,
    ObservabilityConfig,
    PoolConfig,
    RetryConfig,
    TimeoutConfig,
    TlsConfig,
)


@runtime_checkable
class RetrySettingsProtocol(Protocol):
    @property
    def max_attempts(self) -> int: ...

    @property
    def initial_backoff(self) -> float: ...

    @property
    def max_backoff(self) -> float: ...

    @property
    def backoff_multiplier(self) -> float: ...


@runtime_checkable
class CircuitBreakerSettingsProtocol(Protocol):
    @property
    def fail_threshold(self) -> int: ...

    @property
    def recovery_timeout(self) -> float: ...

    @property
    def half_open_max_calls(self) -> int: ...


@runtime_checkable
class ClientSettingsProtocol(Protocol):
    """Mirror of the legacy ``RestClientSettingsProtocol`` reachable surface."""

    @property
    def base_url(self) -> str: ...

    @property
    def timeout_seconds(self) -> float: ...

    @property
    def connect_timeout_seconds(self) -> float: ...

    @property
    def max_connections(self) -> int: ...

    @property
    def max_keepalive_connections(self) -> int: ...

    @property
    def enable_http2(self) -> bool: ...

    @property
    def verify(self) -> bool: ...

    @property
    def logging_enabled(self) -> bool: ...

    @property
    def metrics_enabled(self) -> bool: ...

    @property
    def tracing_enabled(self) -> bool: ...

    @property
    def retry(self) -> RetrySettingsProtocol | None: ...

    @property
    def circuit_breaker(self) -> CircuitBreakerSettingsProtocol | None: ...


def client_config_from_settings(settings: ClientSettingsProtocol, service_name: str) -> ClientConfig:
    """Build a ClientConfig from the structural settings shape used by services."""
    retry_settings = settings.retry
    retry = (
        RetryConfig(
            max_attempts=retry_settings.max_attempts,
            initial_backoff=retry_settings.initial_backoff,
            max_backoff=retry_settings.max_backoff,
            multiplier=retry_settings.backoff_multiplier,
        )
        if retry_settings is not None
        else None
    )
    breaker_settings = settings.circuit_breaker
    circuit_breaker = (
        CircuitBreakerConfig(
            fail_threshold=breaker_settings.fail_threshold,
            recovery_timeout=breaker_settings.recovery_timeout,
            half_open_max_calls=breaker_settings.half_open_max_calls,
        )
        if breaker_settings is not None
        else None
    )
    return ClientConfig(
        service_name=service_name,
        base_url=settings.base_url,
        timeout=TimeoutConfig(total=settings.timeout_seconds, connect=settings.connect_timeout_seconds),
        pool=PoolConfig(
            max_connections=settings.max_connections,
            max_keepalive=settings.max_keepalive_connections,
            http2=settings.enable_http2,
        ),
        retry=retry,
        circuit_breaker=circuit_breaker,
        tls=TlsConfig(verify=settings.verify),
        observability=ObservabilityConfig(
            logging=settings.logging_enabled,
            metrics=settings.metrics_enabled,
            tracing=settings.tracing_enabled,
        ),
    )


__all__ = [
    "CircuitBreakerSettingsProtocol",
    "ClientSettingsProtocol",
    "RetrySettingsProtocol",
    "client_config_from_settings",
]
