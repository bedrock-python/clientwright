"""contrib units: the dishka provider lifecycle."""

from __future__ import annotations

from typing import Annotated, Any

import pytest

pytest.importorskip("dishka", reason="requires the [dishka] extra")
httpx = pytest.importorskip("httpx", reason="requires the [httpx] extra")

from dishka import FromComponent, Provider, Scope, make_async_container, provide  # noqa: E402

import clientwright  # noqa: E402
from clientwright import AdapterDeps, CircuitBreakerConfig, FailureKind, Outcome  # noqa: E402
from clientwright.contrib.dishka import ClientwrightProvider  # noqa: E402
from clientwright.core.plan import ClientHandle, ClientRuntime  # noqa: E402
from clientwright.core.telemetry import names  # noqa: E402


async def test__provider__builds_client_and_closes_it_with_container() -> None:
    config = clientwright.ClientConfig(service_name="di-test")
    container = make_async_container(ClientwrightProvider("httpx", config))
    handle = await container.get(ClientHandle[Any])
    assert type(handle.client) is httpx.AsyncClient
    runtime = await container.get(ClientRuntime)
    assert handle.runtime is runtime  # APP-scope runtime shared through DI
    assert not handle.client.is_closed
    await container.close()
    assert handle.client.is_closed  # the generator provide's finally ran


async def test__request_scope__leaves_the_client_open_until_the_container_closes() -> None:
    # Close travels with the APP-scope provide: a request scope coming and going
    # must not touch the client (the legacy kit parked aclose on a
    # request-scoped exit stack and leaked a client per request).
    config = clientwright.ClientConfig(service_name="di-scope")
    container = make_async_container(ClientwrightProvider("httpx", config))
    async with container() as request:
        handle = await request.get(ClientHandle[Any])
    assert not handle.client.is_closed
    await container.close()
    assert handle.client.is_closed


async def test__two_components__serve_two_upstreams_from_one_container() -> None:
    login = clientwright.ClientConfig(service_name="github-oauth", base_url="https://github.com")
    api = clientwright.ClientConfig(service_name="github-api", base_url="https://api.github.com")
    container = make_async_container(
        ClientwrightProvider("httpx", login, component="github-oauth"),
        ClientwrightProvider("httpx", api, component="github-api"),
    )
    login_handle = await container.get(ClientHandle[Any], component="github-oauth")
    api_handle = await container.get(ClientHandle[Any], component="github-api")
    assert login_handle is not api_handle
    assert login_handle.plan.config.service_name == "github-oauth"
    assert api_handle.plan.config.service_name == "github-api"
    # Each component resolves its own runtime: two upstreams are two breakers.
    assert login_handle.runtime is not api_handle.runtime
    assert login_handle.runtime is await container.get(ClientRuntime, component="github-oauth")
    await container.close()
    assert login_handle.client.is_closed
    assert api_handle.client.is_closed


async def test__client_type__provides_the_native_client_the_handle_holds() -> None:
    config = clientwright.ClientConfig(service_name="di-typed")
    container = make_async_container(ClientwrightProvider("httpx", config, client_type=httpx.AsyncClient))
    client = await container.get(httpx.AsyncClient)
    handle = await container.get(ClientHandle[Any])
    assert client is handle.client
    await container.close()
    assert client.is_closed


class GitHubOAuthProvider:
    """The reporter's shape: two clientwright clients handed to one object."""

    def __init__(
        self,
        login_client: Annotated[httpx.AsyncClient, FromComponent("github-oauth")],
        api_client: Annotated[httpx.AsyncClient, FromComponent("github-api")],
    ) -> None:
        self.login_client = login_client
        self.api_client = api_client


class ServiceProvider(Provider):
    scope = Scope.APP
    github = provide(GitHubOAuthProvider)


async def test__client_type_per_component__injects_each_upstream_by_name() -> None:
    login = clientwright.ClientConfig(service_name="github-oauth", base_url="https://github.com")
    api = clientwright.ClientConfig(service_name="github-api", base_url="https://api.github.com")
    container = make_async_container(
        ClientwrightProvider("httpx", login, component="github-oauth", client_type=httpx.AsyncClient),
        ClientwrightProvider("httpx", api, component="github-api", client_type=httpx.AsyncClient),
        ServiceProvider(),
    )
    github = await container.get(GitHubOAuthProvider)
    login_handle = await container.get(ClientHandle[Any], component="github-oauth")
    api_handle = await container.get(ClientHandle[Any], component="github-api")
    assert github.login_client is login_handle.client
    assert github.api_client is api_handle.client
    await container.close()
    assert github.login_client.is_closed
    assert github.api_client.is_closed


async def test__runtime_built_by_provider__moves_the_circuit_state_gauge() -> None:
    prometheus_client = pytest.importorskip("prometheus_client", reason="requires the [metrics] extra")
    from clientwright.adapters.observability import PrometheusClientMetrics  # noqa: PLC0415 - behind the extra

    registry = prometheus_client.CollectorRegistry()
    config = clientwright.ClientConfig(service_name="di-gauge", circuit_breaker=CircuitBreakerConfig(fail_threshold=1))
    deps = AdapterDeps(metrics=PrometheusClientMetrics(registry=registry))
    container = make_async_container(ClientwrightProvider("httpx", config, deps))
    handle = await container.get(ClientHandle[Any])
    assert handle.runtime.circuits is not None
    handle.runtime.circuits.record("https://wh.example.com:443", Outcome(kind=FailureKind.STATUS, status_code=503))
    labels = {"service": "di-gauge", "adapter": "httpx", "key": "https://wh.example.com:443"}
    assert registry.get_sample_value(names.CIRCUIT_STATE, labels) == 2.0  # open
    await container.close()
