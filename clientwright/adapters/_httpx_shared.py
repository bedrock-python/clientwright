"""Shared machinery of the httpx family: httpx and its successor httpx2.

SDK-agnostic BY CONSTRUCTION: this module never imports httpx or httpx2 (and
stays importable without either extra). Each adapter's modules hand their SDK
namespace in and bind the SDK base classes (byte streams, transports, error
families) to the logic mixins defined here. This is the ONE sanctioned channel
for code sharing between the paired adapters; the import-linter independence
contract still forbids importing a sibling adapter directly.

Public names in both adapters are IDENTICAL on purpose: migrating a service is
one extra and one import path.
"""

from __future__ import annotations

import ssl
from collections.abc import Callable, Mapping, MutableMapping
from typing import Any

from ..core.capabilities import (
    AdapterCapabilities,
    Capability,
    DurationBoundary,
    SeamGranularity,
    Support,
)
from ..core.config import ClientConfig, RedirectMode, is_set, resolve
from ..core.contracts.adapter import AdapterDeps
from ..core.engine.aio import AsyncAttemptEngine
from ..core.engine.sync import SyncAttemptEngine
from ..core.errors import CallError, CircuitOpenError, DeadlineExceededError, TooManyRedirectsError
from ..core.model import IDEMPOTENT_METHODS, ConnMetrics, FailureKind, Outcome, RequestInfo, ResolvedTimeouts, origin_of
from ..core.native import validate_native
from ..core.plan import CallPlan, ClientHandle, ClientRuntime, compile_plan, register_handle
from ..core.policy.timeout import base_timeouts
from ..core.telemetry.emitter import ClientTelemetry

# Per-call extension keys understood by clientwright (identical across the family).
ROUTE_EXTENSION = "clientwright_route"
IDEMPOTENT_EXTENSION = "clientwright_idempotent"

# The family defaults every phase to 5 seconds (DEFAULT_TIMEOUT_CONFIG).
NATIVE_TIMEOUT_DEFAULTS = ResolvedTimeouts(connect=5.0, read=5.0, write=5.0, pool_acquire=5.0)

BODY_HEADERS = ("content-length", "content-type", "transfer-encoding")

RESERVED_CLIENT_KEYS: Mapping[str, str] = {
    "transport": "the transport belongs to clientwright; tune it via config or the 'transport' slot",
    "mounts": "mounts are built by clientwright for proxy routing",
    "timeout": "use ClientConfig.timeout",
    "follow_redirects": "redirects are owned by the engine; use ClientConfig.redirects",
    "max_redirects": "use ClientConfig.max_redirects",
    "limits": "use ClientConfig.pool",
    "http2": "use ClientConfig.pool.http2",
    "verify": "use ClientConfig.tls",
    "cert": "use ClientConfig.tls.cert",
    "proxy": "use ClientConfig.proxy",
    "proxies": "use ClientConfig.proxy",
    "base_url": "use ClientConfig.base_url",
}

RESERVED_TRANSPORT_KEYS: Mapping[str, str] = {
    "verify": "use ClientConfig.tls",
    "cert": "use ClientConfig.tls.cert",
    "http2": "use ClientConfig.pool.http2",
    "limits": "use ClientConfig.pool",
    "proxy": "use ClientConfig.proxy",
    "retries": "retries belong to clientwright; use ClientConfig.retry",
}


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
            "pool_limit_per_host": "Emulated as a per-origin in-flight semaphore; limits requests, not connections.",
            "dns_error": f"{adapter} wraps DNS failures into ConnectError; they surface as connect_error.",
            "proxy_from_env": "Environment proxies are parsed into mounts; NO_PROXY entries match hosts literally.",
        },
    )


def has_ssl_cause(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (ssl.SSLError, ssl.CertificateError)):
            return True
        current = current.__cause__ or current.__context__
    return False


def classify_family_error(sdk: Any, exc: BaseException) -> FailureKind:
    """Exception -> FailureKind for any SDK exposing the httpx error names."""
    import asyncio  # noqa: PLC0415 - stdlib, deferred to keep module import light

    if isinstance(exc, asyncio.CancelledError):
        return FailureKind.CANCELLED
    if isinstance(exc, sdk.ConnectTimeout):
        return FailureKind.CONNECT_TIMEOUT
    if isinstance(exc, sdk.ReadTimeout):
        return FailureKind.READ_TIMEOUT
    if isinstance(exc, sdk.WriteTimeout):
        return FailureKind.WRITE_TIMEOUT
    if isinstance(exc, sdk.PoolTimeout):
        return FailureKind.POOL_TIMEOUT
    if isinstance(exc, sdk.ConnectError):
        return FailureKind.TLS_ERROR if has_ssl_cause(exc) else FailureKind.CONNECT_ERROR
    if isinstance(exc, (sdk.ReadError, sdk.WriteError, sdk.CloseError)):
        return FailureKind.DISCONNECTED
    if isinstance(exc, sdk.RemoteProtocolError):
        # A premature server close arrives as RemoteProtocolError; that is a
        # disconnect (retryable), not a malformed response.
        return FailureKind.DISCONNECTED if "disconnect" in str(exc).lower() else FailureKind.PROTOCOL_ERROR
    if isinstance(exc, sdk.LocalProtocolError):
        return FailureKind.PROTOCOL_ERROR
    if isinstance(exc, sdk.ProxyError):
        return FailureKind.CONNECT_ERROR
    if isinstance(exc, TimeoutError):
        return FailureKind.TOTAL_TIMEOUT
    return FailureKind.UNKNOWN


def make_error_translator(
    circuit_cls: type[CircuitOpenError],
    deadline_cls: type[DeadlineExceededError],
    redirects_cls: type[TooManyRedirectsError],
) -> Callable[[CallError], BaseException]:
    """Build the CallError -> dual-family translator from the bound classes."""

    def translate(error: CallError) -> BaseException:
        if isinstance(error, CircuitOpenError):
            return circuit_cls(error.key, error.retry_after)
        if isinstance(error, DeadlineExceededError):
            return deadline_cls(error.total)
        if isinstance(error, TooManyRedirectsError):
            return redirects_cls(error.hops)
        return error

    return translate


def ssl_arguments(config: ClientConfig) -> dict[str, Any]:
    """TLS kwargs for the transport constructor.

    ``create_ssl_context`` returns early for ``verify=<path>`` and
    ``verify=False``, silently DROPPING the ``cert`` kwarg - so whenever a
    client certificate meets either of those verify modes, the SSLContext is
    baked here (which also surfaces a bad cert path at build time).
    """
    tls = config.tls
    if tls.cert is not None and (tls.ca_bundle is not None or not tls.verify):
        context = ssl.create_default_context(cafile=tls.ca_bundle)
        if not tls.verify and tls.ca_bundle is None:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        if isinstance(tls.cert, str):
            context.load_cert_chain(tls.cert)
        else:
            context.load_cert_chain(*tls.cert)
        return {"verify": context}
    kwargs: dict[str, Any] = {"verify": tls.ca_bundle if tls.ca_bundle is not None else tls.verify}
    if tls.cert is not None:
        kwargs["cert"] = tls.cert
    return kwargs


def timeout_dict(base: ResolvedTimeouts) -> dict[str, float | None]:
    return {"connect": base.connect, "read": base.read, "write": base.write, "pool": base.pool_acquire}


def no_proxy_hosts(proxies: dict[str, str]) -> list[str]:
    raw = proxies.get("no", "")
    return [entry.strip() for entry in raw.split(",") if entry.strip() and entry.strip() != "*"]


def host_bypasses_proxy(host: str, no_proxy: tuple[str, ...]) -> bool:
    for entry in no_proxy:
        candidate = entry.lstrip(".")
        if host == candidate or host.endswith("." + candidate):
            return True
    return False


class FamilyRequestView:
    """Mutable view over a family Request; SDK handed in by the adapter."""

    __slots__ = ("_caller", "_replay_stream", "_request", "_sdk")

    def __init__(
        self,
        request: Any,
        default_timeout: dict[str, float | None],
        *,
        sdk: Any,
        replay_stream: Callable[[bytes], Any],
    ) -> None:
        self._request = request
        self._sdk = sdk
        self._replay_stream = replay_stream
        # Detected ONCE, before the engine's own apply_timeouts mutates the
        # extension - otherwise every redirect hop would misread the engine's
        # previously planned values as a caller override.
        self._caller = self._detect_caller(request, default_timeout)

    @staticmethod
    def _detect_caller(request: Any, default_timeout: dict[str, float | None]) -> ResolvedTimeouts | None:
        current = request.extensions.get("timeout")
        if not isinstance(current, dict) or dict(current) == default_timeout:
            return None
        return ResolvedTimeouts(
            connect=current.get("connect"),
            read=current.get("read"),
            write=current.get("write"),
            pool_acquire=current.get("pool"),
        )

    @property
    def native(self) -> Any:
        return self._request

    @property
    def info(self) -> RequestInfo:
        request = self._request
        url = str(request.url)
        method = request.method
        route = request.extensions.get(ROUTE_EXTENSION)
        idempotent = bool(request.extensions.get(IDEMPOTENT_EXTENSION, method in IDEMPOTENT_METHODS))
        return RequestInfo(
            method=method,
            origin=origin_of(url),
            url=url,
            route=route if isinstance(route, str) else None,
            idempotent=idempotent,
        )

    @property
    def headers(self) -> MutableMapping[str, str]:
        return self._request.headers  # type: ignore[no-any-return]

    def caller_timeouts(self) -> ResolvedTimeouts | None:
        return self._caller

    def apply_timeouts(self, timeouts: ResolvedTimeouts) -> None:
        self._request.extensions["timeout"] = {
            "connect": timeouts.connect,
            "read": timeouts.read,
            "write": timeouts.write,
            "pool": timeouts.pool_acquire,
        }

    def retarget(self, url: str, *, method: str | None = None, drop_body: bool = False) -> None:
        """Mutate the ORIGINAL request in place.

        Identity matters: the client layer holds this very object and later
        does ``response.request = request`` and cookie extraction against its
        URL - a replacement object would leave the final response attributed to
        the pre-redirect URL (cross-origin Set-Cookie would land in the jar
        under the wrong host).
        """
        request = self._request
        target = self._sdk.URL(url)
        request.url = target
        request.headers["host"] = target.netloc.decode("ascii")
        if method is not None:
            request.method = method
        if drop_body:
            for name in BODY_HEADERS:
                request.headers.pop(name, None)
            request.stream = self._replay_stream(b"")
            # Keep .read()/.content consistent with the emptied stream.
            request._content = b""


class FamilyResponseView:
    __slots__ = ("_response",)

    def __init__(self, response: Any) -> None:
        self._response = response

    @property
    def native(self) -> Any:
        return self._response

    @property
    def status_code(self) -> int:
        return self._response.status_code  # type: ignore[no-any-return]

    def header(self, name: str) -> str | None:
        value = self._response.headers.get(name)
        return value if isinstance(value, str) else None

    @property
    def location(self) -> str | None:
        return self.header("location")


class TimedStreamCore:
    """Times body consumption and reports read failures exactly once."""

    def __init__(self, inner: Any, clock: Callable[[], float], on_done: Callable[[Outcome, float], None]) -> None:
        self._inner = inner
        self._clock = clock
        self._on_done = on_done
        self._started = clock()
        self._finished = False

    def _finish(self, outcome: Outcome) -> None:
        if not self._finished:
            self._finished = True
            self._on_done(outcome, self._clock() - self._started)


class AsyncTimedStreamMixin(TimedStreamCore):
    async def __aiter__(self) -> Any:
        try:
            async for chunk in self._inner:
                yield chunk
        except Exception as exc:
            self._finish(Outcome(kind=FailureKind.BODY_ERROR, exception=exc))
            raise
        self._finish(Outcome(kind=None))

    async def aclose(self) -> None:
        try:
            await self._inner.aclose()
        finally:
            self._finish(Outcome(kind=None))


class SyncTimedStreamMixin(TimedStreamCore):
    def __iter__(self) -> Any:
        try:
            yield from self._inner
        except Exception as exc:
            self._finish(Outcome(kind=FailureKind.BODY_ERROR, exception=exc))
            raise
        self._finish(Outcome(kind=None))

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            self._finish(Outcome(kind=None))


class AsyncFamilyNormalizer:
    """Async normalizer template; subclasses bind SDK-specific stream classes."""

    def __init__(
        self,
        default_timeout: dict[str, float | None],
        clock: Callable[[], float],
        *,
        sdk: Any,
        request_view: Callable[[Any], Any],
        timed_stream: Callable[..., Any],
    ) -> None:
        self._default_timeout = default_timeout
        self._clock = clock
        self._sdk = sdk
        self._request_view = request_view
        self._timed_stream = timed_stream

    def wrap_request(self, native: Any) -> Any:
        return self._request_view(native)

    def wrap_response(self, native: Any) -> FamilyResponseView:
        return FamilyResponseView(native)

    def classify_error(self, exc: BaseException) -> FailureKind:
        return classify_family_error(self._sdk, exc)

    def classify_response(self, response: Any) -> Outcome:
        from ..core.engine.base import default_response_outcome  # noqa: PLC0415 - avoid import cycle at module load

        return default_response_outcome(response)

    async def freeze(self, request: Any) -> bool:
        try:
            await request.native.aread()
        except Exception:
            return False
        return True

    async def rewind(self, request: Any) -> None:
        return None

    async def discard(self, response: Any) -> None:
        try:
            await response.native.aclose()
        except Exception:
            return None

    def wrap_stream(self, response: Any, on_done: Callable[[Outcome, float], None]) -> None:
        native = response.native
        stream = native.stream
        if isinstance(stream, self._sdk.AsyncByteStream):
            native.stream = self._timed_stream(stream, self._clock, on_done)

    def conn_metrics(self, response: Any) -> ConnMetrics | None:
        return None


class SyncFamilyNormalizer:
    """Sync twin; blocking body operations."""

    def __init__(
        self,
        default_timeout: dict[str, float | None],
        clock: Callable[[], float],
        *,
        sdk: Any,
        request_view: Callable[[Any], Any],
        timed_stream: Callable[..., Any],
    ) -> None:
        self._default_timeout = default_timeout
        self._clock = clock
        self._sdk = sdk
        self._request_view = request_view
        self._timed_stream = timed_stream

    def wrap_request(self, native: Any) -> Any:
        return self._request_view(native)

    def wrap_response(self, native: Any) -> FamilyResponseView:
        return FamilyResponseView(native)

    def classify_error(self, exc: BaseException) -> FailureKind:
        return classify_family_error(self._sdk, exc)

    def classify_response(self, response: Any) -> Outcome:
        from ..core.engine.base import default_response_outcome  # noqa: PLC0415 - avoid import cycle at module load

        return default_response_outcome(response)

    def freeze(self, request: Any) -> bool:
        try:
            request.native.read()
        except Exception:
            return False
        return True

    def rewind(self, request: Any) -> None:
        return None

    def discard(self, response: Any) -> None:
        try:
            response.native.close()
        except Exception:
            return None

    def wrap_stream(self, response: Any, on_done: Callable[[Outcome, float], None]) -> None:
        native = response.native
        stream = native.stream
        if isinstance(stream, self._sdk.SyncByteStream):
            native.stream = self._timed_stream(stream, self._clock, on_done)

    def conn_metrics(self, response: Any) -> ConnMetrics | None:
        return None


class AsyncEngineTransportMixin:
    """Bound by adapters as ``class T(AsyncEngineTransportMixin, sdk.AsyncBaseTransport)``."""

    def __init__(self, inner: Any, engine: AsyncAttemptEngine) -> None:
        self._inner = inner
        self._engine = engine

    async def _send(self, request: Any) -> Any:
        return await self._inner.handle_async_request(request.native)

    async def handle_async_request(self, request: Any) -> Any:
        return await self._engine.run(request, self._send)

    async def aclose(self) -> None:
        await self._inner.aclose()


class SyncEngineTransportMixin:
    def __init__(self, inner: Any, engine: SyncAttemptEngine) -> None:
        self._inner = inner
        self._engine = engine

    def _send(self, request: Any) -> Any:
        return self._inner.handle_request(request.native)

    def handle_request(self, request: Any) -> Any:
        return self._engine.run(request, self._send)

    def close(self) -> None:
        self._inner.close()


class AsyncProxyRouterMixin:
    """Routes every request - including owned-redirect hops - to the right proxy.

    Client-level mounts are resolved by the client ONCE per logical call,
    before the engine's redirect loop; this router sits INSIDE the engine seam
    instead, so a hop that crosses schemes or lands on a NO_PROXY host
    re-routes correctly.
    """

    def __init__(self, direct: Any, by_scheme: dict[str, Any], no_proxy_hosts: tuple[str, ...]) -> None:
        self._direct = direct
        self._by_scheme = by_scheme
        self._no_proxy_hosts = no_proxy_hosts

    def _pick(self, url: Any) -> Any:
        if host_bypasses_proxy(url.host, self._no_proxy_hosts):
            return self._direct
        return self._by_scheme.get(url.scheme, self._direct)

    async def handle_async_request(self, request: Any) -> Any:
        return await self._pick(request.url).handle_async_request(request)

    async def aclose(self) -> None:
        await self._direct.aclose()
        for transport in self._by_scheme.values():
            await transport.aclose()


class SyncProxyRouterMixin:
    def __init__(self, direct: Any, by_scheme: dict[str, Any], no_proxy_hosts: tuple[str, ...]) -> None:
        self._direct = direct
        self._by_scheme = by_scheme
        self._no_proxy_hosts = no_proxy_hosts

    def _pick(self, url: Any) -> Any:
        if host_bypasses_proxy(url.host, self._no_proxy_hosts):
            return self._direct
        return self._by_scheme.get(url.scheme, self._direct)

    def handle_request(self, request: Any) -> Any:
        return self._pick(request.url).handle_request(request)

    def close(self) -> None:
        self._direct.close()
        for transport in self._by_scheme.values():
            transport.close()


class FamilyAdapter:
    """The whole builder, shared; subclasses bind SDK and SDK-based classes."""

    # Bound by each adapter:
    name: str
    capabilities: AdapterCapabilities
    sdk: Any
    async_normalizer: Callable[[dict[str, float | None], Callable[[], float]], Any]
    sync_normalizer: Callable[[dict[str, float | None], Callable[[], float]], Any]
    async_engine_transport: Callable[[Any, AsyncAttemptEngine], Any]
    sync_engine_transport: Callable[[Any, SyncAttemptEngine], Any]
    async_proxy_router: Callable[[Any, dict[str, Any], tuple[str, ...]], Any]
    sync_proxy_router: Callable[[Any, dict[str, Any], tuple[str, ...]], Any]
    translate: Callable[[CallError], BaseException]

    native_slots = frozenset({"client", "transport"})
    reserved_keys: Mapping[str, Mapping[str, str]] = {
        "client": RESERVED_CLIENT_KEYS,
        "transport": RESERVED_TRANSPORT_KEYS,
    }
    allowed_keys: Mapping[str, frozenset[str] | None] = {"client": None, "transport": None}

    def _validated_native(self, config: ClientConfig, *, sync: bool) -> dict[str, dict[str, Any]]:
        client_target = self.sdk.Client if sync else self.sdk.AsyncClient
        transport_target = self.sdk.HTTPTransport if sync else self.sdk.AsyncHTTPTransport
        return validate_native(
            config.native,
            slots=self.native_slots,
            reserved=self.reserved_keys,
            allowed=self.allowed_keys,
            signature_targets={"client": client_target, "transport": transport_target},
            config_conflicts={},
        )

    def _compile(self, config: ClientConfig, *, sync: bool) -> CallPlan:
        applied = {
            Capability.TIMEOUT_CONNECT,
            Capability.TIMEOUT_READ,
            Capability.TIMEOUT_WRITE,
            Capability.TIMEOUT_POOL,
            Capability.POOL_LIMIT_TOTAL,
            Capability.KEEPALIVE,
            Capability.REDIRECTS_OWNABLE,
        }
        if resolve(config.pool.http2, False):
            applied.add(Capability.HTTP2)
        if config.proxy is not None:
            applied.add(Capability.PROXY)
        emulated = {Capability.TIMEOUT_TOTAL}
        dropped: dict[Capability, str] = {}
        if sync:
            # The sync engine cannot cancel a blocked socket call: no hard
            # deadline, no per-attempt ceiling. Saying so in the report is the
            # whole point of the report.
            if is_set(config.timeout.attempt) and resolve(config.timeout.attempt, None) is not None:
                dropped[Capability.TIMEOUT_ATTEMPT] = (
                    "sync engine cannot cancel a blocked attempt; only phase timeouts and the soft total apply"
                )
        else:
            emulated |= {Capability.TIMEOUT_ATTEMPT, Capability.DEADLINE_HARD}
        if resolve(config.pool.max_connections_per_host, None) is not None:
            emulated.add(Capability.POOL_LIMIT_PER_HOST)
        plan = compile_plan(
            config,
            self.capabilities,
            native_timeout_defaults=NATIVE_TIMEOUT_DEFAULTS,
            applied_natively=frozenset(applied),
            emulated=frozenset(emulated),
            dropped=dropped,
        )
        plan.report.enforce(config.on_unsupported)
        return plan

    def _limits(self, config: ClientConfig) -> Any:
        return self.sdk.Limits(
            max_connections=resolve(config.pool.max_connections, 100),
            max_keepalive_connections=resolve(config.pool.max_keepalive, 20),
            keepalive_expiry=resolve(config.pool.keepalive_expiry, 5.0),
        )

    def _client_timeout(self, base: ResolvedTimeouts) -> Any:
        return self.sdk.Timeout(connect=base.connect, read=base.read, write=base.write, pool=base.pool_acquire)

    def _transport_kwargs(self, config: ClientConfig, native_transport: dict[str, Any]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "http2": resolve(config.pool.http2, False),
            "limits": self._limits(config),
        }
        kwargs.update(ssl_arguments(config))
        kwargs.update(native_transport)
        return kwargs

    def _telemetry(self, config: ClientConfig, deps: AdapterDeps) -> ClientTelemetry:
        return ClientTelemetry(
            service=config.service_name,
            adapter=self.name,
            seam=self.capabilities.seam,
            config=config.observability,
            metrics=deps.metrics,
            tracer=deps.tracer,
        )

    def build_async(self, config: ClientConfig, deps: AdapterDeps) -> ClientHandle[Any]:
        from urllib.request import getproxies  # noqa: PLC0415 - stdlib, deferred for import cost

        sdk = self.sdk
        native = self._validated_native(config, sync=False)
        telemetry = self._telemetry(config, deps)
        runtime = deps.runtime or ClientRuntime.for_config(
            config, clock=deps.clock, circuit_listener=telemetry.circuit_state_changed
        )
        plan = self._compile(config, sync=False)
        base = base_timeouts(config.timeout, NATIVE_TIMEOUT_DEFAULTS)
        engine = AsyncAttemptEngine(
            plan=plan,
            runtime=runtime,
            telemetry=telemetry,
            normalizer=type(self).async_normalizer(timeout_dict(base), runtime.clock),
            deps=deps,
            translate=type(self).translate,
        )
        transport_kwargs = self._transport_kwargs(config, native.get("transport", {}))

        def make_raw(proxy: str | None) -> Any:
            return sdk.AsyncHTTPTransport(proxy=proxy, **transport_kwargs)

        explicit_proxy = config.proxy.url if config.proxy is not None else None
        inner: Any = make_raw(explicit_proxy)
        if config.proxy is not None and config.proxy.from_env:
            proxies = getproxies()
            by_scheme: dict[str, Any] = {
                scheme: make_raw(proxies[scheme]) for scheme in ("http", "https") if scheme in proxies
            }
            if by_scheme:
                # The router sits INSIDE the engine seam, so every owned-redirect
                # hop re-routes through the right proxy (client-level mounts are
                # resolved only once per logical call).
                inner = type(self).async_proxy_router(make_raw(None), by_scheme, tuple(no_proxy_hosts(proxies)))
        transport = type(self).async_engine_transport(inner, engine)
        client = sdk.AsyncClient(
            base_url=config.base_url or "",
            transport=transport,
            follow_redirects=config.redirects is RedirectMode.NATIVE,
            max_redirects=config.max_redirects,
            timeout=self._client_timeout(base),
            **native.get("client", {}),
        )
        handle: ClientHandle[Any] = ClientHandle(
            client=client,
            adapter=self.name,
            capabilities=self.capabilities,
            report=plan.report,
            runtime=runtime,
            plan=plan,
            aclose=client.aclose,
        )
        register_handle(client, handle)
        return handle

    def build_sync(self, config: ClientConfig, deps: AdapterDeps) -> ClientHandle[Any]:
        from urllib.request import getproxies  # noqa: PLC0415 - stdlib, deferred for import cost

        sdk = self.sdk
        native = self._validated_native(config, sync=True)
        telemetry = self._telemetry(config, deps)
        runtime = deps.runtime or ClientRuntime.for_config(
            config, clock=deps.clock, circuit_listener=telemetry.circuit_state_changed
        )
        plan = self._compile(config, sync=True)
        base = base_timeouts(config.timeout, NATIVE_TIMEOUT_DEFAULTS)
        engine = SyncAttemptEngine(
            plan=plan,
            runtime=runtime,
            telemetry=telemetry,
            normalizer=type(self).sync_normalizer(timeout_dict(base), runtime.clock),
            deps=deps,
            translate=type(self).translate,
        )
        transport_kwargs = self._transport_kwargs(config, native.get("transport", {}))

        def make_raw(proxy: str | None) -> Any:
            return sdk.HTTPTransport(proxy=proxy, **transport_kwargs)

        explicit_proxy = config.proxy.url if config.proxy is not None else None
        inner: Any = make_raw(explicit_proxy)
        if config.proxy is not None and config.proxy.from_env:
            proxies = getproxies()
            by_scheme: dict[str, Any] = {
                scheme: make_raw(proxies[scheme]) for scheme in ("http", "https") if scheme in proxies
            }
            if by_scheme:
                inner = type(self).sync_proxy_router(make_raw(None), by_scheme, tuple(no_proxy_hosts(proxies)))
        transport = type(self).sync_engine_transport(inner, engine)
        client = sdk.Client(
            base_url=config.base_url or "",
            transport=transport,
            follow_redirects=config.redirects is RedirectMode.NATIVE,
            max_redirects=config.max_redirects,
            timeout=self._client_timeout(base),
            **native.get("client", {}),
        )
        handle: ClientHandle[Any] = ClientHandle(
            client=client,
            adapter=self.name,
            capabilities=self.capabilities,
            report=plan.report,
            runtime=runtime,
            plan=plan,
            close=client.close,
        )
        register_handle(client, handle)
        return handle


__all__ = [
    "BODY_HEADERS",
    "IDEMPOTENT_EXTENSION",
    "NATIVE_TIMEOUT_DEFAULTS",
    "RESERVED_CLIENT_KEYS",
    "RESERVED_TRANSPORT_KEYS",
    "ROUTE_EXTENSION",
    "AsyncEngineTransportMixin",
    "AsyncFamilyNormalizer",
    "AsyncProxyRouterMixin",
    "AsyncTimedStreamMixin",
    "FamilyAdapter",
    "FamilyRequestView",
    "FamilyResponseView",
    "SyncEngineTransportMixin",
    "SyncFamilyNormalizer",
    "SyncProxyRouterMixin",
    "SyncTimedStreamMixin",
    "TimedStreamCore",
    "capabilities_for",
    "classify_family_error",
    "host_bypasses_proxy",
    "make_error_translator",
    "no_proxy_hosts",
    "ssl_arguments",
    "timeout_dict",
]
