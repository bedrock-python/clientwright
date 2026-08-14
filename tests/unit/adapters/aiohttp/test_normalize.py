"""aiohttp normalizer edge paths: the replayability probe and discard resilience."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

aiohttp = pytest.importorskip("aiohttp", reason="requires the [aiohttp] extra")

from clientwright.adapters.aiohttp.normalize import AsyncAiohttpNormalizer  # noqa: E402


class _View:
    """Minimal RequestView/ResponseView stand-in: the probes only touch ``.native``."""

    def __init__(self, native: Any) -> None:
        self.native = native


async def test__freeze__true_when_the_request_has_no_body() -> None:
    normalizer = AsyncAiohttpNormalizer()
    assert await normalizer.freeze(_View(SimpleNamespace(body=None))) is True  # type: ignore[arg-type]


async def test__freeze__true_for_raw_bytes_bodies() -> None:
    normalizer = AsyncAiohttpNormalizer()
    assert await normalizer.freeze(_View(SimpleNamespace(body=b"payload"))) is True  # type: ignore[arg-type]


async def test__freeze__false_for_an_unknown_streaming_body() -> None:
    normalizer = AsyncAiohttpNormalizer()
    assert await normalizer.freeze(_View(SimpleNamespace(body=object()))) is False  # type: ignore[arg-type]


async def test__discard__swallows_a_failing_release() -> None:
    class _Response:
        def release(self) -> None:
            raise RuntimeError("connection already gone")

    normalizer = AsyncAiohttpNormalizer()
    assert await normalizer.discard(_View(_Response())) is None  # type: ignore[arg-type]


async def test__discard__awaits_an_awaitable_release() -> None:
    released: list[bool] = []

    class _Response:
        async def release(self) -> None:
            released.append(True)

    normalizer = AsyncAiohttpNormalizer()
    assert await normalizer.discard(_View(_Response())) is None  # type: ignore[arg-type]
    assert released == [True]
