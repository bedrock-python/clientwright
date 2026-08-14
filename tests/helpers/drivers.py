"""Uniform adapter drivers for the cross-adapter batteries (parity, chaos).

Each driver hides one SDK's calling convention behind the same tiny surface, so
a battery scenario is written once and runs verbatim against every adapter.
Drivers import their SDK lazily; batteries skip missing ones via
``adapter_params``.
"""

from __future__ import annotations

import importlib.util
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

import pytest

import clientwright
from clientwright import AdapterDeps, ClientConfig
from clientwright.core.options import call_options
from clientwright.core.testing import OriginServer, RecordingMetrics


@dataclass(frozen=True, slots=True)
class DriverResponse:
    status: int
    body: bytes


_MODULE_OF = {
    "httpx": "httpx",
    "httpx-sync": "httpx",
    "httpx2": "httpx2",
    "aiohttp": "aiohttp",
    "requests": "requests",
    "urllib3": "urllib3",
}

ASYNC_ADAPTERS = ("httpx", "httpx2", "aiohttp")
SYNC_ADAPTERS = ("httpx-sync", "requests", "urllib3")


def adapter_params(names: tuple[str, ...]) -> list[Any]:
    params = []
    for name in names:
        module = _MODULE_OF[name]
        params.append(
            pytest.param(
                name,
                marks=pytest.mark.skipif(
                    importlib.util.find_spec(module) is None, reason=f"requires the [{module}] extra"
                ),
            )
        )
    return params


class HttpxAsyncDriver:
    """httpx family carries per-call options in request extensions, not the ambient channel."""

    name = "httpx"
    sdk = "httpx"
    supports_base_url = True

    def family_errors(self) -> tuple[type[BaseException], ...]:
        return (importlib.import_module(self.sdk).HTTPError, TimeoutError)

    def _extensions(self, idempotent: bool | None) -> dict[str, Any] | None:
        if idempotent is None:
            return None
        adapter = importlib.import_module(f"clientwright.adapters.{self.sdk}")
        return {adapter.IDEMPOTENT_EXTENSION: idempotent}

    def build(self, config: ClientConfig, deps: AdapterDeps) -> Any:
        return clientwright.build(self.sdk, config, deps)

    async def request(
        self,
        client: Any,
        origin_url: str,
        method: str,
        path: str,
        *,
        idempotent: bool | None = None,
        body: bytes | None = None,
    ) -> DriverResponse:
        response = await client.request(method, path, content=body, extensions=self._extensions(idempotent))
        return DriverResponse(response.status_code, response.content)

    async def close(self, client: Any) -> None:
        await client.aclose()


class Httpx2Driver(HttpxAsyncDriver):
    name = "httpx2"
    sdk = "httpx2"


class AiohttpDriver:
    name = "aiohttp"
    supports_base_url = True

    def family_errors(self) -> tuple[type[BaseException], ...]:
        aiohttp = importlib.import_module("aiohttp")
        return (aiohttp.ClientError, TimeoutError)

    def build(self, config: ClientConfig, deps: AdapterDeps) -> Any:
        return clientwright.build("aiohttp", config, deps)

    async def request(
        self,
        client: Any,
        origin_url: str,
        method: str,
        path: str,
        *,
        idempotent: bool | None = None,
        body: bytes | None = None,
    ) -> DriverResponse:
        options = call_options(idempotent=idempotent) if idempotent is not None else nullcontext()
        with options:
            response = await client.request(method, path, data=body)
        payload = await response.read()
        return DriverResponse(response.status, payload)

    async def close(self, client: Any) -> None:
        await client.close()


class HttpxSyncDriver(HttpxAsyncDriver):
    name = "httpx-sync"
    sdk = "httpx"

    def build(self, config: ClientConfig, deps: AdapterDeps) -> Any:
        return clientwright.build_sync(self.sdk, config, deps)

    def request(  # type: ignore[override]
        self,
        client: Any,
        origin_url: str,
        method: str,
        path: str,
        *,
        idempotent: bool | None = None,
        body: bytes | None = None,
    ) -> DriverResponse:
        response = client.request(method, path, content=body, extensions=self._extensions(idempotent))
        return DriverResponse(response.status_code, response.content)

    def close(self, client: Any) -> None:  # type: ignore[override]
        client.close()


class RequestsDriver:
    name = "requests"
    supports_base_url = False

    def family_errors(self) -> tuple[type[BaseException], ...]:
        requests = importlib.import_module("requests")
        return (requests.RequestException, TimeoutError)

    def build(self, config: ClientConfig, deps: AdapterDeps) -> Any:
        return clientwright.build_sync("requests", config, deps)

    def request(
        self,
        client: Any,
        origin_url: str,
        method: str,
        path: str,
        *,
        idempotent: bool | None = None,
        body: bytes | None = None,
    ) -> DriverResponse:
        options = call_options(idempotent=idempotent) if idempotent is not None else nullcontext()
        with options:
            response = client.request(method, origin_url + path, data=body)
        return DriverResponse(response.status_code, response.content)

    def close(self, client: Any) -> None:
        client.close()


class Urllib3Driver:
    name = "urllib3"
    supports_base_url = False

    def family_errors(self) -> tuple[type[BaseException], ...]:
        urllib3 = importlib.import_module("urllib3")
        return (urllib3.exceptions.HTTPError, TimeoutError)

    def build(self, config: ClientConfig, deps: AdapterDeps) -> Any:
        return clientwright.build_sync("urllib3", config, deps)

    def request(
        self,
        client: Any,
        origin_url: str,
        method: str,
        path: str,
        *,
        idempotent: bool | None = None,
        body: bytes | None = None,
    ) -> DriverResponse:
        options = call_options(idempotent=idempotent) if idempotent is not None else nullcontext()
        with options:
            response = client.request(method, origin_url + path, body=body)
        return DriverResponse(response.status, response.data)

    def close(self, client: Any) -> None:
        client.clear()


_DRIVERS: dict[str, Any] = {
    "httpx": HttpxAsyncDriver(),
    "httpx2": Httpx2Driver(),
    "aiohttp": AiohttpDriver(),
    "httpx-sync": HttpxSyncDriver(),
    "requests": RequestsDriver(),
    "urllib3": Urllib3Driver(),
}


def get_driver(name: str) -> Any:
    return _DRIVERS[name]


def battery_config(driver: Any, origin: OriginServer, **overrides: object) -> ClientConfig:
    """One config shape for every adapter; base_url only where the SDK has one."""
    settings: dict[str, object] = {"service_name": f"battery-{driver.name}"}
    if driver.supports_base_url:
        settings["base_url"] = origin.url
    settings.update(overrides)
    return ClientConfig(**settings)  # type: ignore[arg-type]


def fresh_deps() -> tuple[RecordingMetrics, AdapterDeps]:
    metrics = RecordingMetrics()
    return metrics, AdapterDeps(metrics=metrics)


__all__ = [
    "ASYNC_ADAPTERS",
    "SYNC_ADAPTERS",
    "DriverResponse",
    "adapter_params",
    "battery_config",
    "fresh_deps",
    "get_driver",
]
