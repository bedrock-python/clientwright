"""clientwright: one resilience and observability core, many HTTP clients.

``build()`` returns the REAL native client of the chosen adapter - a genuine
``httpx.AsyncClient``, not a wrapper - with retries, circuit breaking, owned
redirects, deadlines and telemetry wired UNDER its public API. ``inspect()``
returns the handle with the config-application report and runtime state.

A bare install is a working install: the core has zero dependencies; adapters
and observability backends load lazily behind extras.
"""

from typing import Any

from .__version__ import __version__
from .core.capabilities import (
    AdapterCapabilities,
    Capability,
    ConfigApplicationReport,
    DurationBoundary,
    SeamGranularity,
    Support,
    capabilities_matrix,
)
from .core.config import (
    DEFAULT_RETRYABLE_KINDS,
    DEFAULT_RETRYABLE_STATUS,
    DEFAULT_SENSITIVE_HEADERS,
    DEFAULT_SENSITIVE_QUERY_PARAMS,
    DEFAULT_TRIP_KINDS,
    UNSET,
    CallerOverride,
    CircuitBreakerConfig,
    ClientConfig,
    Maybe,
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
    is_set,
)
from .core.contracts import (
    AdapterDeps,
    CircuitBreakerSettingsProtocol,
    ClientAdapter,
    ClientMetricsProtocol,
    ClientSettingsProtocol,
    DeadlineSource,
    HeaderProvider,
    MaskerProtocol,
    RetrySettingsProtocol,
    SpanProtocol,
    TracerProtocol,
)
from .core.contracts.adapter import default_deps
from .core.contracts.settings import client_config_from_settings
from .core.errors import (
    CallError,
    CircuitOpenError,
    ClientwrightError,
    DeadlineExceededError,
    NativeConfigError,
    NotReplayableError,
    TooManyRedirectsError,
    UnknownAdapterError,
    UnsupportedCapabilityError,
)
from .core.model import IDEMPOTENT_METHODS, CircuitKey, FailureKind, Outcome, RequestInfo, ResolvedTimeouts
from .core.options import CallOptions, call_options, current_call_options
from .core.plan import ClientHandle, ClientRuntime, inspect_client
from .core.registry import register_adapter, registered_adapters, resolve_adapter

# The builders are typed ``Any`` deliberately. The whole product is "you get the
# REAL native client", and the core cannot name ``httpx.AsyncClient`` without
# taking a dependency on it - so a narrower type would be a lie that forces a
# cast on every caller. ``Any`` lets `client: httpx.AsyncClient = build(...)`
# type-check, which is exactly what the tutorial promises.


def build_handle(adapter: str, config: ClientConfig, deps: AdapterDeps | None = None) -> ClientHandle[Any]:
    """Build an ASYNC native client and return its full handle."""
    adapter_cls = resolve_adapter(adapter)
    return adapter_cls().build_async(config, deps or default_deps())  # type: ignore[no-any-return]


def build(adapter: str, config: ClientConfig, deps: AdapterDeps | None = None) -> Any:
    """Build an ASYNC native client (e.g. a genuine ``httpx.AsyncClient``)."""
    return build_handle(adapter, config, deps).client


def build_sync_handle(adapter: str, config: ClientConfig, deps: AdapterDeps | None = None) -> ClientHandle[Any]:
    """Build a SYNC native client and return its full handle."""
    adapter_cls = resolve_adapter(adapter)
    return adapter_cls().build_sync(config, deps or default_deps())  # type: ignore[no-any-return]


def build_sync(adapter: str, config: ClientConfig, deps: AdapterDeps | None = None) -> Any:
    """Build a SYNC native client (e.g. a genuine ``httpx.Client``)."""
    return build_sync_handle(adapter, config, deps).client


inspect = inspect_client

__all__ = [
    "DEFAULT_RETRYABLE_KINDS",
    "DEFAULT_RETRYABLE_STATUS",
    "DEFAULT_SENSITIVE_HEADERS",
    "DEFAULT_SENSITIVE_QUERY_PARAMS",
    "DEFAULT_TRIP_KINDS",
    "IDEMPOTENT_METHODS",
    "UNSET",
    "AdapterCapabilities",
    "AdapterDeps",
    "CallError",
    "CallOptions",
    "CallerOverride",
    "Capability",
    "CircuitBreakerConfig",
    "CircuitBreakerSettingsProtocol",
    "CircuitKey",
    "CircuitOpenError",
    "ClientAdapter",
    "ClientConfig",
    "ClientHandle",
    "ClientMetricsProtocol",
    "ClientRuntime",
    "ClientSettingsProtocol",
    "ClientwrightError",
    "ConfigApplicationReport",
    "DeadlineExceededError",
    "DeadlineSource",
    "DurationBoundary",
    "FailureKind",
    "HeaderProvider",
    "MaskerProtocol",
    "Maybe",
    "NativeConfigError",
    "NativeOptions",
    "NotReplayableError",
    "ObservabilityConfig",
    "Outcome",
    "PoolConfig",
    "ProxyConfig",
    "RedirectMode",
    "RequestInfo",
    "ResolvedTimeouts",
    "RetryConfig",
    "RetryMode",
    "RetrySettingsProtocol",
    "SeamGranularity",
    "SpanProtocol",
    "Support",
    "TimeoutConfig",
    "TlsConfig",
    "TooManyRedirectsError",
    "TracerProtocol",
    "UnknownAdapterError",
    "UnsupportedCapabilityError",
    "UnsupportedPolicy",
    "__version__",
    "build",
    "build_handle",
    "build_sync",
    "build_sync_handle",
    "call_options",
    "capabilities_matrix",
    "client_config_from_settings",
    "current_call_options",
    "default_deps",
    "inspect",
    "inspect_client",
    "is_set",
    "register_adapter",
    "registered_adapters",
    "resolve_adapter",
]
