"""Sync normalizer: the whole requests-specific contract for the sync engine."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...core.contracts.message import RequestView, ResponseView
from ...core.engine.base import default_response_outcome
from ...core.model import ConnMetrics, FailureKind, Outcome
from ._imports import requests
from .classify import classify_error
from .views import RequestsRequestView, RequestsResponseView


class SyncRequestsNormalizer:
    def wrap_request(self, native: Any) -> RequestsRequestView:
        return RequestsRequestView(native)

    def wrap_response(self, native: Any) -> RequestsResponseView:
        return RequestsResponseView(native)

    def classify_error(self, exc: BaseException) -> FailureKind:
        return classify_error(exc)

    def classify_response(self, response: ResponseView) -> Outcome:
        return default_response_outcome(response)

    def freeze(self, request: RequestView) -> bool:
        """Bytes and strings replay for free; seekable streams rewind, the rest do not."""
        body = request.native.body
        if body is None or isinstance(body, (bytes, str)):
            return True
        position = getattr(request.native, "_body_position", None)
        return isinstance(position, int)

    def rewind(self, request: RequestView) -> None:
        body = request.native.body
        if body is None or isinstance(body, (bytes, str)):
            return None
        try:
            requests.utils.rewind_body(request.native)
        except requests.exceptions.UnrewindableBodyError:  # pragma: no cover - freeze() gated this
            return None
        return None

    def discard(self, response: ResponseView) -> None:
        """MANDATORY before a repeat - otherwise the connection never returns to the pool."""
        try:
            response.native.close()
        except Exception:
            return None

    def wrap_stream(self, response: ResponseView, on_done: Callable[[Outcome, float], None]) -> None:
        # Session.send consumes the body ABOVE this seam (unless stream=True);
        # body read is not instrumented. Declared in capabilities.
        return None

    def conn_metrics(self, response: ResponseView) -> ConnMetrics | None:
        return None


__all__ = ["SyncRequestsNormalizer"]
