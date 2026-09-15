"""servicewright's request context flowing through the engine against a real origin."""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="requires the [httpx] extra")
servicewright = pytest.importorskip("servicewright", reason="requires the [servicewright] extra")

import clientwright  # noqa: E402
from clientwright import AdapterDeps  # noqa: E402
from clientwright.contrib.servicewright import servicewright_headers  # noqa: E402
from clientwright.core.testing import OriginServer  # noqa: E402

from ..conftest import base_config  # noqa: E402


async def test__bound_context__travels_as_headers_and_only_while_bound(origin: OriginServer) -> None:
    wired = AdapterDeps(header_providers=servicewright_headers())
    client = clientwright.build("httpx", base_config(origin), wired)
    assert isinstance(client, httpx.AsyncClient)
    with servicewright.bind_context(request_id="rid-1", tenant_id="acme"):
        bound = (await client.get("/echo")).json()["headers"]
    outside = (await client.get("/echo")).json()["headers"]
    await client.aclose()
    assert bound["x-request-id"] == "rid-1"
    assert bound["x-tenant-id"] == "acme"
    assert "x-request-id" not in outside
    assert "x-tenant-id" not in outside
