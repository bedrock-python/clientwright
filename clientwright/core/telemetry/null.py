"""Null observability backends: emitters never branch on ``is None``."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping


class NullMetrics:
    """Accepts every record and does nothing."""

    def record_call(
        self,
        *,
        service: str,
        adapter: str,
        seam: str,
        method: str,
        origin: str,
        route: str,
        status: str,
        outcome: str,
        duration: float,
    ) -> None:
        return None

    def record_body_duration(
        self,
        *,
        service: str,
        adapter: str,
        seam: str,
        method: str,
        origin: str,
        route: str,
        duration: float,
    ) -> None:
        return None

    def record_attempt(
        self,
        *,
        service: str,
        adapter: str,
        seam: str,
        method: str,
        origin: str,
        outcome: str,
        duration: float,
    ) -> None:
        return None

    def inflight_delta(self, *, service: str, adapter: str, seam: str, origin: str, delta: int) -> None:
        return None

    def record_circuit_state(self, *, service: str, adapter: str, key: str, state: str) -> None:
        return None

    def record_redirect_hop(self, *, service: str, adapter: str, seam: str) -> None:
        return None

    def record_retry_skipped(self, *, service: str, adapter: str, seam: str, reason: str) -> None:
        return None

    def record_uninstrumented_call(self, *, service: str, adapter: str, seam: str) -> None:
        return None


class NullSpan:
    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        return None

    def record_failure(self, description: str) -> None:
        return None

    def end(self) -> None:
        return None


class NullTracer:
    _SPAN = NullSpan()

    def start_span(self, name: str, *, attributes: Mapping[str, str | int | float | bool]) -> NullSpan:
        return self._SPAN

    def inject_context(self, headers: MutableMapping[str, str]) -> None:
        return None


__all__ = ["NullMetrics", "NullSpan", "NullTracer"]
