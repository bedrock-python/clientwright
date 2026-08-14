"""Async normalizer: the whole aiohttp-specific contract for the async engine."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from ...core.contracts.message import RequestView, ResponseView
from ...core.engine.base import default_response_outcome
from ...core.model import ConnMetrics, FailureKind, Outcome
from ._imports import aiohttp
from .classify import classify_error
from .trace import current_conn_metrics
from .views import AiohttpRequestView, AiohttpResponseView


class AsyncAiohttpNormalizer:
    def wrap_request(self, native: Any) -> AiohttpRequestView:
        return AiohttpRequestView(native)

    def wrap_response(self, native: Any) -> AiohttpResponseView:
        return AiohttpResponseView(native)

    def classify_error(self, exc: BaseException) -> FailureKind:
        return classify_error(exc)

    def classify_response(self, response: ResponseView) -> Outcome:
        return default_response_outcome(response)

    async def freeze(self, request: RequestView) -> bool:
        """Bytes-backed payloads replay for free; streams and files do not."""
        body = request.native.body
        if body is None:
            return True
        if isinstance(body, (bytes, bytearray, memoryview)):
            return True
        if isinstance(body, aiohttp.payload.BytesPayload):
            return not bool(getattr(body, "consumed", False))
        return False

    async def rewind(self, request: RequestView) -> None:
        # BytesPayload re-emits its full content on every send; nothing to do.
        return None

    async def discard(self, response: ResponseView) -> None:
        """MANDATORY before a repeat - otherwise the connection never returns to the pool."""
        try:
            result = response.native.release()
            if inspect.isawaitable(result):
                await result
        except Exception:
            return None

    def wrap_stream(self, response: ResponseView, on_done: Callable[[Outcome, float], None]) -> None:
        # The middleware returns at headers; the body streams outside the seam.
        # Declared in capabilities (note "body_duration"), not silently skipped.
        return None

    def conn_metrics(self, response: ResponseView) -> ConnMetrics | None:
        return current_conn_metrics()


__all__ = ["AsyncAiohttpNormalizer"]
