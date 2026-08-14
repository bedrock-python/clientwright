"""Sync normalizer: the whole urllib3-specific contract for the sync engine."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...core.contracts.message import RequestView, ResponseView
from ...core.engine.base import default_response_outcome
from ...core.model import ConnMetrics, FailureKind, Outcome
from .classify import classify_error
from .views import Urllib3RequestView, Urllib3ResponseView


class SyncUrllib3Normalizer:
    def wrap_request(self, native: Any) -> Urllib3RequestView:
        return Urllib3RequestView(native)

    def wrap_response(self, native: Any) -> Urllib3ResponseView:
        return Urllib3ResponseView(native)

    def classify_error(self, exc: BaseException) -> FailureKind:
        return classify_error(exc)

    def classify_response(self, response: ResponseView) -> Outcome:
        return default_response_outcome(response)

    def freeze(self, request: RequestView) -> bool:
        body = request.native.body
        return body is None or isinstance(body, (bytes, str))

    def rewind(self, request: RequestView) -> None:
        return None

    def discard(self, response: ResponseView) -> None:
        """MANDATORY before a repeat - otherwise the connection never returns to the pool."""
        try:
            response.native.drain_conn()
        except Exception:
            return None

    def wrap_stream(self, response: ResponseView, on_done: Callable[[Outcome, float], None]) -> None:
        # urlopen preloads the body by default; streaming reads happen above
        # the seam and are not instrumented. Declared in capabilities.
        return None

    def conn_metrics(self, response: ResponseView) -> ConnMetrics | None:
        return None


__all__ = ["SyncUrllib3Normalizer"]
