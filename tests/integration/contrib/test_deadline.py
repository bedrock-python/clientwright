"""The ambient deadline budget flowing through the engine against a real origin."""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="requires the [httpx] extra")

import clientwright  # noqa: E402
from clientwright import AdapterDeps  # noqa: E402
from clientwright.contrib.deadline import AmbientDeadlineSource, use_budget  # noqa: E402
from clientwright.core.testing import OriginServer  # noqa: E402

from ..conftest import base_config  # noqa: E402


class FakeBudget:
    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    def remaining(self) -> float:
        return self._seconds

    def expired(self) -> bool:
        return self._seconds <= 0


async def test__budget__caps_the_call_below_the_configured_total(origin: OriginServer, deps: AdapterDeps) -> None:
    wired = AdapterDeps(metrics=deps.metrics, deadline_source=AmbientDeadlineSource())
    client = clientwright.build("httpx", base_config(origin, retry=None), wired)
    assert isinstance(client, httpx.AsyncClient)
    with use_budget(FakeBudget(0.5)), pytest.raises(httpx.TimeoutException):
        # config total is 30s; the ambient budget of 0.5s wins.
        await client.get("/slow/3")
    response = await client.get("/echo")  # outside the block: unbounded by budget
    assert response.status_code == 200
    await client.aclose()


async def test__deadline_header__reflects_the_ambient_budget(origin: OriginServer) -> None:
    wired = AdapterDeps(deadline_source=AmbientDeadlineSource())
    config = base_config(origin, deadline_header="X-Deadline-Ms")
    client = clientwright.build("httpx", config, wired)
    assert isinstance(client, httpx.AsyncClient)
    with use_budget(FakeBudget(2.0)):
        response = await client.get("/echo")
    stamped = int(response.json()["headers"]["x-deadline-ms"])
    assert 0 < stamped <= 2_000  # the header carries the budget remainder, not the config total
    await client.aclose()
