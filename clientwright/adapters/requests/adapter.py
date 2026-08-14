"""The requests adapter: builds real Session objects with the engine underneath.

The seam is a mounted ``HTTPAdapter`` subclass whose ``send()`` runs the
engine; the returned object is a genuine ``requests.Session``. Two constraints
this builder honors (verified against requests 2.32):

- requests has NO session-level timeout default - a bare ``session.get()``
  hangs forever; the engine sends every attempt with its planned
  ``(connect, read)`` tuple, closing that hole;
- native retries execute INSIDE ``conn.urlopen``, invisible to metrics and the
  breaker - they are pinned to ``Retry(0, read=False)`` and the engine owns
  the loop.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...core.capabilities import Capability
from ...core.config import ClientConfig, is_set, resolve
from ...core.contracts.adapter import AdapterDeps
from ...core.contracts.message import RequestView
from ...core.engine.suppress import is_suppressed, suppressed
from ...core.engine.sync import SyncAttemptEngine
from ...core.errors import UnsupportedCapabilityError
from ...core.model import ResolvedTimeouts
from ...core.native import validate_native
from ...core.plan import CallPlan, ClientHandle, ClientRuntime, compile_plan, register_handle
from ...core.telemetry.emitter import ClientTelemetry
from ._imports import HTTPAdapter, requests, urllib3
from .capabilities import CAPABILITIES
from .errors import translate_call_error
from .normalize import SyncRequestsNormalizer
from .views import CALLER_TIMEOUT_ATTRIBUTE, RequestsRequestView

# requests has no timeout defaults at all: an UNSET phase stays unbounded and
# only the engine's total deadline clamps it.
_NATIVE_TIMEOUT_DEFAULTS = ResolvedTimeouts()

_SESSION_ATTRS = frozenset({"headers", "cookies", "auth", "params", "hooks", "stream", "trust_env"})

_RESERVED_SESSION_KEYS: Mapping[str, str] = {
    "verify": "use ClientConfig.tls",
    "cert": "use ClientConfig.tls.cert",
    "proxies": "use ClientConfig.proxy",
    "max_redirects": "use ClientConfig.max_redirects",
    "adapters": "the mounted adapters belong to clientwright",
}

_RESERVED_ADAPTER_KEYS: Mapping[str, str] = {
    "max_retries": "retries belong to clientwright; use ClientConfig.retry",
    "pool_connections": "use ClientConfig.pool",
    "pool_maxsize": "use ClientConfig.pool.max_connections_per_host",
    "pool_block": "use ClientConfig.pool.max_connections_per_host",
}


class EngineHTTPAdapter(HTTPAdapter):
    """HTTPAdapter whose send() is one engine-driven logical call."""

    def __init__(self, engine: SyncAttemptEngine, **kwargs: Any) -> None:
        kwargs.setdefault("max_retries", urllib3.util.Retry(0, read=False))
        super().__init__(**kwargs)
        self._engine = engine

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: bool | str = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> requests.Response:
        if is_suppressed():
            # An outer clientwright layer owns instrumentation for this call.
            return super().send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies)
        setattr(request, CALLER_TIMEOUT_ATTRIBUTE, timeout)

        def send_view(view: RequestView) -> requests.Response:
            planned = view.planned if isinstance(view, RequestsRequestView) else None
            attempt_timeout = (planned.connect, planned.read) if planned is not None else timeout
            with suppressed():
                return super(EngineHTTPAdapter, self).send(
                    view.native, stream=stream, timeout=attempt_timeout, verify=verify, cert=cert, proxies=proxies
                )

        response = self._engine.run(request, send_view)
        assert isinstance(response, requests.Response)
        return response


class RequestsAdapter:
    name = "requests"
    capabilities = CAPABILITIES
    native_slots = frozenset({"session", "adapter"})
    reserved_keys: Mapping[str, Mapping[str, str]] = {
        "session": _RESERVED_SESSION_KEYS,
        "adapter": _RESERVED_ADAPTER_KEYS,
    }
    allowed_keys: Mapping[str, frozenset[str] | None] = {"session": _SESSION_ATTRS, "adapter": None}

    def _validated_native(self, config: ClientConfig) -> dict[str, dict[str, Any]]:
        return validate_native(
            config.native,
            slots=self.native_slots,
            reserved=self.reserved_keys,
            allowed=self.allowed_keys,
            signature_targets={"adapter": HTTPAdapter},
            config_conflicts={},
        )

    def _compile(self, config: ClientConfig) -> CallPlan:
        applied = {Capability.TIMEOUT_CONNECT, Capability.TIMEOUT_READ, Capability.REDIRECTS_OWNABLE}
        if resolve(config.pool.max_connections_per_host, None) is not None:
            applied.add(Capability.POOL_LIMIT_PER_HOST)
        if config.proxy is not None:
            applied.add(Capability.PROXY)
        emulated = {Capability.TIMEOUT_TOTAL}
        dropped: dict[Capability, str] = {}
        if is_set(config.timeout.attempt) and resolve(config.timeout.attempt, None) is not None:
            dropped[Capability.TIMEOUT_ATTEMPT] = (
                "sync engine cannot cancel a blocked attempt; only phase timeouts and the soft total apply"
            )
        if is_set(config.timeout.write) and resolve(config.timeout.write, None) is not None:
            dropped[Capability.TIMEOUT_WRITE] = "requests has no write timeout"
        if is_set(config.timeout.pool_acquire) and resolve(config.timeout.pool_acquire, None) is not None:
            dropped[Capability.TIMEOUT_POOL] = "HTTPAdapter.send never forwards pool_timeout to urllib3"
        if resolve(config.pool.http2, False):
            dropped[Capability.HTTP2] = "requests speaks HTTP/1.1 only"
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

    def build_sync(self, config: ClientConfig, deps: AdapterDeps) -> ClientHandle[Any]:
        if config.base_url is not None:
            raise UnsupportedCapabilityError("requests has no base_url; pass absolute URLs (or use the httpx adapter)")
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
            normalizer=SyncRequestsNormalizer(),
            deps=deps,
            translate=translate_call_error,
        )
        per_host = resolve(config.pool.max_connections_per_host, None)
        adapter_kwargs: dict[str, Any] = {
            "pool_maxsize": per_host if per_host is not None else resolve(config.pool.max_connections, 10) or 10,
            "pool_block": per_host is not None,
        }
        adapter_kwargs.update(native.get("adapter", {}))
        engine_adapter = EngineHTTPAdapter(engine, **adapter_kwargs)
        session = requests.Session()
        session.mount("http://", engine_adapter)
        session.mount("https://", engine_adapter)
        session.verify = config.tls.ca_bundle if config.tls.ca_bundle is not None else config.tls.verify
        cert = config.tls.cert
        if isinstance(cert, tuple) and len(cert) == 3:
            raise UnsupportedCapabilityError("requests does not support a client cert with a key password")
        session.cert = cert
        session.max_redirects = config.max_redirects
        if config.proxy is not None and config.proxy.url is not None:
            session.proxies.update({"http": config.proxy.url, "https": config.proxy.url})
        # config.proxy.from_env needs nothing: requests reads env proxies natively.
        for attr, value in native.get("session", {}).items():
            setattr(session, attr, value)
        handle: ClientHandle[Any] = ClientHandle(
            client=session,
            adapter=self.name,
            capabilities=CAPABILITIES,
            report=plan.report,
            runtime=runtime,
            plan=plan,
            close=session.close,
        )
        register_handle(session, handle)
        return handle

    def build_async(self, config: ClientConfig, deps: AdapterDeps) -> ClientHandle[Any]:
        raise UnsupportedCapabilityError(
            "requests is sync-only: there is no async client to build; use build_sync (or the httpx/aiohttp adapters)"
        )


__all__ = ["EngineHTTPAdapter", "RequestsAdapter"]
