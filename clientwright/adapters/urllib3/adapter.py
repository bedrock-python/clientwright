"""The urllib3 adapter: builds real PoolManager objects with the engine underneath.

The seam is a per-instance ``urlopen`` injected on a GENUINE ``PoolManager``
(``type(client) is urllib3.PoolManager`` holds - no subclass); recursive
native calls and lower clientwright layers pass straight through via the
suppression ContextVar.

This is also the documented home of ``RetryMode.DELEGATED``: urllib3's Retry
is the richest native implementation, so a config in DELEGATED mode is
translated into ``urllib3.util.Retry`` and the native machinery runs the loop
below the seam - with per-attempt metrics honestly absent.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...core.capabilities import Capability
from ...core.config import ClientConfig, RetryConfig, RetryMode, is_set, resolve
from ...core.contracts.adapter import AdapterDeps
from ...core.contracts.message import RequestView
from ...core.engine.suppress import is_suppressed, suppressed
from ...core.engine.sync import SyncAttemptEngine
from ...core.errors import UnsupportedCapabilityError
from ...core.model import ResolvedTimeouts
from ...core.native import validate_native
from ...core.plan import CallPlan, ClientHandle, ClientRuntime, compile_plan, register_handle
from ...core.policy.timeout import base_timeouts
from ...core.telemetry.emitter import ClientTelemetry
from ._imports import Retry, Timeout, urllib3
from .capabilities import CAPABILITIES
from .errors import translate_call_error
from .normalize import SyncUrllib3Normalizer
from .views import Urllib3CallSpec, Urllib3RequestView

# urllib3 defaults timeouts to socket.getdefaulttimeout() (usually unbounded).
_NATIVE_TIMEOUT_DEFAULTS = ResolvedTimeouts()

_RESERVED_MANAGER_KEYS: Mapping[str, str] = {
    "timeout": "use ClientConfig.timeout",
    "retries": "retries belong to clientwright; use ClientConfig.retry (mode=DELEGATED for native execution)",
    "maxsize": "use ClientConfig.pool.max_connections_per_host",
    "block": "use ClientConfig.pool.max_connections_per_host",
    "cert_reqs": "use ClientConfig.tls",
    "ca_certs": "use ClientConfig.tls.ca_bundle",
    "cert_file": "use ClientConfig.tls.cert",
    "key_file": "use ClientConfig.tls.cert",
}


def translate_retry(retry: RetryConfig, max_redirects: int) -> Retry:
    """Express RetryConfig as urllib3.util.Retry for DELEGATED mode.

    urllib3's exponential backoff base is fixed at 2; ``multiplier`` is not
    translated (declared in the capabilities notes).
    """
    return Retry(
        total=retry.max_attempts - 1,
        redirect=max_redirects,
        backoff_factor=retry.initial_backoff,
        backoff_max=retry.max_backoff,
        backoff_jitter=retry.jitter * retry.initial_backoff,
        status_forcelist=set(retry.retryable_status),
        allowed_methods=frozenset(retry.methods),
        respect_retry_after_header=retry.respect_retry_after,
        raise_on_status=False,
        raise_on_redirect=False,
    )


class EngineUrlopen:
    """The instance-injected urlopen: one call in, one engine-driven logical call out."""

    __slots__ = ("_blocking", "_delegated_retry", "_engine", "_manager")

    def __init__(
        self,
        manager: urllib3.PoolManager,
        engine: SyncAttemptEngine,
        delegated_retry: Retry | None,
        blocking_pool: bool,
    ) -> None:
        self._manager = manager
        self._engine = engine
        self._delegated_retry = delegated_retry
        self._blocking = blocking_pool

    def _native_urlopen(self, method: str, url: str, **kw: Any) -> Any:
        return type(self._manager).urlopen(self._manager, method, url, **kw)

    def _send(self, view: RequestView) -> Any:
        assert isinstance(view, Urllib3RequestView)
        spec = view.native
        kw = dict(spec.kw)
        kw["headers"] = dict(spec.headers)
        kw["body"] = spec.body
        if self._delegated_retry is not None:
            # Native machinery owns retries AND redirects below the seam.
            kw["retries"] = self._delegated_retry
            kw.setdefault("redirect", True)
        else:
            # The engine owns the loop: raw errors, no native retry, no native
            # redirect following (hops re-enter through retarget()).
            kw["retries"] = False
            kw["redirect"] = False
        planned = spec.planned
        if planned is not None:
            kw["timeout"] = Timeout(connect=planned.connect, read=planned.read)
            if self._blocking and planned.pool_acquire is not None:
                kw.setdefault("pool_timeout", planned.pool_acquire)
        with suppressed():
            return self._native_urlopen(spec.method, spec.url, **kw)

    def __call__(self, method: str, url: str, redirect: bool = True, **kw: Any) -> Any:
        if is_suppressed():
            # A recursive native hop, or an outer clientwright layer that owns
            # instrumentation: pass straight through.
            return self._native_urlopen(method, url, redirect=redirect, **kw)
        headers_arg = kw.pop("headers", None)
        headers = dict(headers_arg) if headers_arg is not None else dict(self._manager.headers or {})
        body = kw.pop("body", None)
        spec = Urllib3CallSpec(method, url, headers, body, kw)
        return self._engine.run(spec, self._send)


class Urllib3Adapter:
    name = "urllib3"
    capabilities = CAPABILITIES
    native_slots = frozenset({"manager"})
    reserved_keys: Mapping[str, Mapping[str, str]] = {"manager": _RESERVED_MANAGER_KEYS}
    allowed_keys: Mapping[str, frozenset[str] | None] = {"manager": None}

    def _validated_native(self, config: ClientConfig) -> dict[str, dict[str, Any]]:
        return validate_native(
            config.native,
            slots=self.native_slots,
            reserved=self.reserved_keys,
            allowed=self.allowed_keys,
            signature_targets={"manager": urllib3.HTTPConnectionPool},
            config_conflicts={},
        )

    def _compile(self, config: ClientConfig) -> CallPlan:
        per_host = resolve(config.pool.max_connections_per_host, None)
        applied = {Capability.TIMEOUT_CONNECT, Capability.TIMEOUT_READ, Capability.REDIRECTS_OWNABLE}
        if per_host is not None:
            applied |= {Capability.POOL_LIMIT_PER_HOST, Capability.TIMEOUT_POOL}
        if config.proxy is not None and config.proxy.url is not None:
            applied.add(Capability.PROXY)
        emulated = {Capability.TIMEOUT_TOTAL}
        dropped: dict[Capability, str] = {}
        if is_set(config.timeout.attempt) and resolve(config.timeout.attempt, None) is not None:
            dropped[Capability.TIMEOUT_ATTEMPT] = (
                "sync engine cannot cancel a blocked attempt; only phase timeouts and the soft total apply"
            )
        if is_set(config.timeout.write) and resolve(config.timeout.write, None) is not None:
            dropped[Capability.TIMEOUT_WRITE] = "urllib3 has no write timeout"
        pool_acquire_set = (
            is_set(config.timeout.pool_acquire) and resolve(config.timeout.pool_acquire, None) is not None
        )
        if per_host is None and pool_acquire_set:
            dropped[Capability.TIMEOUT_POOL] = "pool_timeout needs a blocking pool; set pool.max_connections_per_host"
        if resolve(config.pool.http2, False):
            dropped[Capability.HTTP2] = "urllib3's HTTP/2 support is experimental and not wired here"
        if config.proxy is not None and config.proxy.from_env:
            dropped[Capability.PROXY] = "urllib3 does not read environment proxies; pass ProxyConfig.url"
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

    def _manager_kwargs(self, config: ClientConfig, native_manager: dict[str, Any]) -> dict[str, Any]:
        per_host = resolve(config.pool.max_connections_per_host, None)
        base = base_timeouts(config.timeout, _NATIVE_TIMEOUT_DEFAULTS)
        kwargs: dict[str, Any] = {
            "maxsize": per_host if per_host is not None else resolve(config.pool.max_connections, 10) or 10,
            "block": per_host is not None,
            # A defensive default for calls that bypass the engine (suppressed
            # native hops); the engine overrides timeout per attempt anyway.
            "timeout": Timeout(connect=base.connect, read=base.read),
        }
        tls = config.tls
        if not tls.verify:
            kwargs["cert_reqs"] = "CERT_NONE"
        if tls.ca_bundle is not None:
            kwargs["ca_certs"] = tls.ca_bundle
        if tls.cert is not None:
            if isinstance(tls.cert, str):
                kwargs["cert_file"] = tls.cert
            else:
                kwargs["cert_file"] = tls.cert[0]
                kwargs["key_file"] = tls.cert[1]
        kwargs.update(native_manager)
        return kwargs

    def build_sync(self, config: ClientConfig, deps: AdapterDeps) -> ClientHandle[Any]:
        if config.base_url is not None:
            raise UnsupportedCapabilityError("urllib3 has no base_url; pass absolute URLs (or use the httpx adapter)")
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
        engine = SyncAttemptEngine(
            plan=plan,
            runtime=runtime,
            telemetry=telemetry,
            normalizer=SyncUrllib3Normalizer(),
            deps=deps,
            translate=translate_call_error,
        )
        manager_kwargs = self._manager_kwargs(config, native.get("manager", {}))
        manager: urllib3.PoolManager
        if config.proxy is not None and config.proxy.url is not None:
            manager = urllib3.ProxyManager(config.proxy.url, **manager_kwargs)
        else:
            manager = urllib3.PoolManager(**manager_kwargs)
        delegated = config.retry is not None and config.retry.mode is RetryMode.DELEGATED
        delegated_retry = (
            translate_retry(config.retry, config.max_redirects) if delegated and config.retry is not None else None
        )
        per_host = resolve(config.pool.max_connections_per_host, None)
        # The instance attribute shadows the class method for every entry point
        # (request/request_encode_* all funnel into self.urlopen), while
        # type(manager) stays the genuine native class.
        manager.urlopen = EngineUrlopen(manager, engine, delegated_retry, per_host is not None)  # type: ignore[method-assign]
        handle: ClientHandle[Any] = ClientHandle(
            client=manager,
            adapter=self.name,
            capabilities=CAPABILITIES,
            report=plan.report,
            runtime=runtime,
            plan=plan,
            close=manager.clear,
        )
        register_handle(manager, handle)
        return handle

    def build_async(self, config: ClientConfig, deps: AdapterDeps) -> ClientHandle[Any]:
        raise UnsupportedCapabilityError(
            "urllib3 is sync-only: there is no async client to build; use build_sync (or the httpx/aiohttp adapters)"
        )


__all__ = ["EngineUrlopen", "Urllib3Adapter", "translate_retry"]
