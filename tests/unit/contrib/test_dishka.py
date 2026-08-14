"""contrib units: the dishka provider lifecycle."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("dishka", reason="requires the [dishka] extra")
httpx = pytest.importorskip("httpx", reason="requires the [httpx] extra")

from dishka import make_async_container  # noqa: E402

import clientwright  # noqa: E402
from clientwright.contrib.dishka import ClientwrightProvider  # noqa: E402
from clientwright.core.plan import ClientHandle, ClientRuntime  # noqa: E402


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
