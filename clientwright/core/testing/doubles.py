"""Deterministic doubles for engine and telemetry tests."""

from __future__ import annotations

from dataclasses import dataclass, field


class ManualClock:
    """Monotonic clock advanced by hand."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@dataclass(slots=True)
class RecordingMetrics:
    """ClientMetricsProtocol implementation that remembers every record."""

    calls: list[dict[str, object]] = field(default_factory=list)
    attempts: list[dict[str, object]] = field(default_factory=list)
    body_durations: list[dict[str, object]] = field(default_factory=list)
    inflight: list[dict[str, object]] = field(default_factory=list)
    circuit_states: list[dict[str, object]] = field(default_factory=list)
    redirect_hops: list[dict[str, object]] = field(default_factory=list)
    retry_skips: list[dict[str, object]] = field(default_factory=list)
    uninstrumented: list[dict[str, object]] = field(default_factory=list)

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
        self.calls.append(
            {
                "service": service,
                "adapter": adapter,
                "seam": seam,
                "method": method,
                "origin": origin,
                "route": route,
                "status": status,
                "outcome": outcome,
                "duration": duration,
            }
        )

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
        self.body_durations.append({"method": method, "origin": origin, "route": route, "duration": duration})

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
        self.attempts.append({"method": method, "origin": origin, "outcome": outcome, "duration": duration})

    def inflight_delta(self, *, service: str, adapter: str, seam: str, origin: str, delta: int) -> None:
        self.inflight.append({"origin": origin, "delta": delta})

    def record_circuit_state(self, *, service: str, adapter: str, key: str, state: str) -> None:
        self.circuit_states.append({"key": key, "state": state})

    def record_redirect_hop(self, *, service: str, adapter: str, seam: str) -> None:
        self.redirect_hops.append({"adapter": adapter})

    def record_retry_skipped(self, *, service: str, adapter: str, seam: str, reason: str) -> None:
        self.retry_skips.append({"reason": reason})

    def record_uninstrumented_call(self, *, service: str, adapter: str, seam: str) -> None:
        self.uninstrumented.append({"adapter": adapter})

    @property
    def inflight_balance(self) -> int:
        return sum(int(record["delta"]) for record in self.inflight)  # type: ignore[call-overload]


__all__ = ["ManualClock", "RecordingMetrics"]
