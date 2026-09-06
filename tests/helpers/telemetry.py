"""Telemetry doubles: a tracer that keeps every span it opened."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field


@dataclass(slots=True)
class RecordingSpan:
    """SpanProtocol double keeping every attribute the emitter sets."""

    attributes: dict[str, object] = field(default_factory=dict)
    ended: bool = False

    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        self.attributes[key] = value

    def record_failure(self, description: str) -> None:
        self.attributes["failure"] = description

    def end(self) -> None:
        self.ended = True


@dataclass(slots=True)
class RecordingTracer:
    """TracerProtocol double; one RecordingSpan per logical call."""

    spans: list[RecordingSpan] = field(default_factory=list)

    def start_span(self, name: str, *, attributes: Mapping[str, str | int | float | bool]) -> RecordingSpan:
        span = RecordingSpan(attributes=dict(attributes))
        self.spans.append(span)
        return span

    def inject_context(self, headers: MutableMapping[str, str]) -> None:
        return


__all__ = ["RecordingSpan", "RecordingTracer"]
