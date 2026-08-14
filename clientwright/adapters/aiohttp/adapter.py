"""The aiohttp adapter: builds real ClientSession objects with the engine underneath.

aiohttp constraints this builder honors (verified against aiohttp 3.12):
- the session-level total timeout would wrap ALL our retries and backoff sleeps
  (middleware runs inside the ``_request`` timer), so ``ClientTimeout.total``
  is always None and the engine's monotonic deadline is the only total;
- ``ceil_threshold`` is raised so aiohttp never rounds deadlines up to whole
  seconds (the default ceils everything above 5s);
- the native one-shot idempotent retry is invisible to middleware and is
  silenced via the private ``_retry_connection`` attribute (declared DEGRADED);
- ``ClientSession`` must be constructed inside a running event loop.
"""

from __future__ import annotations

import ssl
from collections.abc import Mapping
from typing import Any
from urllib.request import getproxies

from ...core.capabilities import Capability
from ...core.config import ClientConfig, is_set, resolve
from ...core.contracts.adapter import AdapterDeps
from ...core.engine.aio import AsyncAttemptEngine
from ...core.errors import UnsupportedCapabilityError
from ...core.model import ResolvedTimeouts
from ...core.native import validate_native
from ...core.plan import CallPlan, ClientHandle, ClientRuntime, compile_plan, register_handle
from ...core.policy.timeout import base_timeouts
from ...core.telemetry.emitter import ClientTelemetry
from ._imports import aiohttp
from .capabilities import CAPABILITIES
from .errors import translate_call_error
from .middleware import EngineMiddleware, ProxyRouter
from .normalize import AsyncAiohttpNormalizer
from .trace import build_trace_config

# aiohttp's DEFAULT_TIMEOUT is ClientTimeout(total=5*60, sock_connect=30); the
# closest per-phase reading: 30s to connect, no read/write/pool phases.
_NATIVE_TIMEOUT_DEFAULTS = ResolvedTimeouts(connect=30.0, read=None, write=None, pool_acquire=None)

# Above this threshold aiohttp ceils absolute deadlines to whole seconds; a
# value no timeout reaches disables the rounding entirely.
_NO_CEIL_THRESHOLD = 1e9

_RESERVED_SESSION_KEYS: Mapping[str, str] = {
    "connector": "the connector is built by clientwright; tune it via config or the 'connector' slot",
    "connector_owner": "clientwright owns the connector lifecycle",
    "middlewares": "middlewares belong to clientwright; the engine seam lives there",
    "trace_configs": "trace_configs belong to clientwright (bypass sentinel and conn metrics)",
    "timeout": "use ClientConfig.timeout",
    "base_url": "use ClientConfig.base_url",
    "headers": "use ClientConfig.headers",
    "proxy": "use ClientConfig.proxy",
}

_RESERVED_CONNECTOR_KEYS: Mapping[str, str] = {
    "limit": "use ClientConfig.pool.max_connections",
    "limit_per_host": "use ClientConfig.pool.max_connections_per_host",
    "keepalive_timeout": "use ClientConfig.pool.keepalive_expiry",
    "force_close": "use ClientConfig.pool.keepalive_expiry=None",
    "ssl": "use ClientConfig.tls",
}


def _ssl_argument(config: ClientConfig) -> ssl.SSLContext | bool:
    tls = config.tls
    if tls.ca_bundle is None and tls.cert is None:
        return bool(tls.verify)
    context = ssl.create_default_context(cafile=tls.ca_bundle)
    if not tls.verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    if tls.cert is not None:
        if isinstance(tls.cert, str):
            context.load_cert_chain(tls.cert)
        else:
            context.load_cert_chain(*tls.cert)
    return context


def _no_proxy_hosts(proxies: dict[str, str]) -> tuple[str, ...]:
    raw = proxies.get("no", "")
    return tuple(entry.strip() for entry in raw.split(",") if entry.strip() and entry.strip() != "*")


def _proxy_router(config: ClientConfig) -> ProxyRouter | None:
    if config.proxy is None:
        return None
    if config.proxy.url is not None:
        return ProxyRouter(config.proxy.url)
    proxies = getproxies()
    by_scheme: dict[str, str] = {scheme: proxies[scheme] for scheme in ("http", "https") if scheme in proxies}
    if not by_scheme:
        return None
    return ProxyRouter(None, by_scheme, _no_proxy_hosts(proxies))


class AiohttpAdapter:
    name = "aiohttp"
    capabilities = CAPABILITIES
    native_slots = frozenset({"session", "connector"})
    reserved_keys: Mapping[str, Mapping[str, str]] = {
        "session": _RESERVED_SESSION_KEYS,
        "connector": _RESERVED_CONNECTOR_KEYS,
    }
    allowed_keys: Mapping[str, frozenset[str] | None] = {"session": None, "connector": None}

    def _validated_native(self, config: ClientConfig) -> dict[str, dict[str, Any]]:
        return validate_native(
            config.native,
            slots=self.native_slots,
            reserved=self.reserved_keys,
            allowed=self.allowed_keys,
            signature_targets={"session": aiohttp.ClientSession, "connector": aiohttp.TCPConnector},
            config_conflicts={},
        )

    def _compile(self, config: ClientConfig) -> CallPlan:
        applied = {
            Capability.TIMEOUT_CONNECT,
            Capability.TIMEOUT_READ,
            Capability.POOL_LIMIT_TOTAL,
            Capability.KEEPALIVE,
        }
        if resolve(config.pool.max_connections_per_host, None) is not None:
            applied.add(Capability.POOL_LIMIT_PER_HOST)
        emulated = {Capability.TIMEOUT_TOTAL, Capability.TIMEOUT_ATTEMPT, Capability.DEADLINE_HARD}
        if config.proxy is not None:
            emulated.add(Capability.PROXY)
        dropped: dict[Capability, str] = {}
        if is_set(config.timeout.write) and resolve(config.timeout.write, None) is not None:
            dropped[Capability.TIMEOUT_WRITE] = (
                "aiohttp has no write timeout; a slow upload is bounded only by the attempt ceiling"
            )
        if is_set(config.timeout.pool_acquire) and resolve(config.timeout.pool_acquire, None) is not None:
            dropped[Capability.TIMEOUT_POOL] = (
                "aiohttp folds pool waiting into the connect phase; there is no separate pool timeout"
            )
        if resolve(config.pool.http2, False):
            dropped[Capability.HTTP2] = "aiohttp speaks HTTP/1.1 only"
        plan = compile_plan(
            config,
            CAPABILITIES,
            native_timeout_defaults=_NATIVE_TIMEOUT_DEFAULTS,
            applied_natively=frozenset(applied),
            emulated=frozenset(emulated),
            dropped=dropped,
        )
        plan.report.enforce(config.on_unsupported)
        return plan

    def _connector(self, config: ClientConfig, native_connector: dict[str, Any]) -> aiohttp.TCPConnector:
        limit = resolve(config.pool.max_connections, 100)
        per_host = resolve(config.pool.max_connections_per_host, None)
        keepalive = resolve(config.pool.keepalive_expiry, 15.0)
        kwargs: dict[str, Any] = {
            "limit": 0 if limit is None else limit,
            "limit_per_host": 0 if per_host is None else per_host,
            "ssl": _ssl_argument(config),
        }
        if keepalive is None:
            kwargs["force_close"] = True
        else:
            kwargs["keepalive_timeout"] = keepalive
        kwargs.update(native_connector)
        return aiohttp.TCPConnector(**kwargs)

    def build_async(self, config: ClientConfig, deps: AdapterDeps) -> ClientHandle[Any]:
        native = self._validated_native(config)
        telemetry = ClientTelemetry(
            service=config.service_name,
            adapter=self.name,
            seam=CAPABILITIES.seam,
            config=config.observability,
            metrics=deps.metrics,
            tracer=deps.tracer,
        )
        runtime = deps.runtime or ClientRuntime.for_config(
            config, clock=deps.clock, circuit_listener=telemetry.circuit_state_changed
        )
        plan = self._compile(config)
        base = base_timeouts(config.timeout, _NATIVE_TIMEOUT_DEFAULTS)
        engine = AsyncAttemptEngine(
            plan=plan,
            runtime=runtime,
            telemetry=telemetry,
            normalizer=AsyncAiohttpNormalizer(),
            deps=deps,
            translate=translate_call_error,
        )
        middleware = EngineMiddleware(engine, _proxy_router(config))
        # total=None ON PURPOSE: aiohttp's total timer would wrap the engine's
        # whole retry loop, sleeps included. The engine's deadline is the total.
        client_timeout = aiohttp.ClientTimeout(
            total=None,
            connect=base.connect,
            sock_read=base.read,
            ceil_threshold=_NO_CEIL_THRESHOLD,
        )
        session_kwargs: dict[str, Any] = dict(native.get("session", {}))
        if config.base_url is not None:
            session_kwargs["base_url"] = config.base_url
        session = aiohttp.ClientSession(
            connector=self._connector(config, native.get("connector", {})),
            timeout=client_timeout,
            middlewares=(middleware,),
            trace_configs=[build_trace_config(telemetry, runtime.clock)],
            **session_kwargs,
        )
        try:
            # The hidden one-shot idempotent retry would multiply our attempt
            # count outside the metrics; the name is listed in ClientSession.ATTRS.
            session._retry_connection = False
        except AttributeError:  # pragma: no cover - future aiohttp may drop the attribute
            pass
        handle: ClientHandle[Any] = ClientHandle(
            client=session,
            adapter=self.name,
            capabilities=CAPABILITIES,
            report=plan.report,
            runtime=runtime,
            plan=plan,
            aclose=session.close,
        )
        register_handle(session, handle)
        return handle

    def build_sync(self, config: ClientConfig, deps: AdapterDeps) -> ClientHandle[Any]:
        raise UnsupportedCapabilityError(
            "aiohttp is async-only: there is no sync client to build; use build() or build_handle(), "
            "or pick an adapter with a sync flavor (httpx, requests, urllib3)"
        )


__all__ = ["AiohttpAdapter"]
