"""Value-level URL masking: the MaskerProtocol seam in the emitter."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

import pytest

from clientwright.core.config import ObservabilityConfig
from clientwright.core.model import Outcome, RequestInfo
from clientwright.core.telemetry.emitter import ClientTelemetry
from clientwright.core.telemetry.redaction import REDACTED

# redact_url reassembles the query with urlencode, so the marker comes out
# percent-encoded inside URLs.
REDACTED_IN_URL = quote_plus(REDACTED)

if TYPE_CHECKING:
    from collections.abc import Mapping

INFO = RequestInfo(
    method="GET",
    origin="https://a:443",
    url="https://a/users/alex@example.com/orders?token=x",
    route="/users/{id}/orders",
)


@dataclass(slots=True)
class RecordingSpan:
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
    spans: list[RecordingSpan] = field(default_factory=list)

    def start_span(self, name: str, *, attributes: Mapping[str, str | int | float | bool]) -> RecordingSpan:
        span = RecordingSpan(attributes=dict(attributes))
        self.spans.append(span)
        return span

    def inject_context(self, headers: dict[str, str]) -> None:  # pragma: no cover - unused
        return


def telemetry(config: ObservabilityConfig, tracer: RecordingTracer | None = None) -> ClientTelemetry:
    return ClientTelemetry(service="svc", adapter="fake", seam="test", config=config, metrics=None, tracer=tracer)


# --- masker applied ---


def test__masker__runs_after_query_redaction_and_reaches_span_and_log(caplog: pytest.LogCaptureFixture) -> None:
    seen: list[str] = []

    def masker(value: str) -> str:
        seen.append(value)
        return value.replace("alex@example.com", "***")

    tracer = RecordingTracer()
    config = ObservabilityConfig(sensitive_query_params=frozenset({"token"}), url_masker=masker)
    emitter = telemetry(config, tracer)

    with caplog.at_level(logging.DEBUG, logger="clientwright.client.svc"):
        observation = emitter.call_start(INFO, started=0.0)
        emitter.call_end(observation, INFO, Outcome(kind=None, status_code=200), duration=0.1)

    # The masker saw the query already redacted by name - never the raw token.
    assert seen and all("token=x" not in value for value in seen)
    assert all(f"token={REDACTED_IN_URL}" in value for value in seen)
    # PII in the path segment is gone from the span and from every log record.
    masked = f"https://a/users/***/orders?token={REDACTED_IN_URL}"
    assert tracer.spans[0].attributes["url.full"] == masked
    urls = [record.url for record in caplog.records if hasattr(record, "url")]
    assert urls and all(url == masked for url in urls)


def test__masker_none__url_unchanged_beyond_query_redaction() -> None:
    tracer = RecordingTracer()
    config = ObservabilityConfig(sensitive_query_params=frozenset({"token"}))
    emitter = telemetry(config, tracer)
    observation = emitter.call_start(INFO, started=0.0)
    emitter.call_end(observation, INFO, Outcome(kind=None, status_code=200), duration=0.1)
    assert tracer.spans[0].attributes["url.full"] == f"https://a/users/alex@example.com/orders?token={REDACTED_IN_URL}"


# --- fail closed ---


def test__masker_raises__emits_redacted_and_never_breaks_the_call(caplog: pytest.LogCaptureFixture) -> None:
    def broken(value: str) -> str:
        raise RuntimeError("model not loaded")

    tracer = RecordingTracer()
    emitter = telemetry(ObservabilityConfig(url_masker=broken), tracer)

    with caplog.at_level(logging.DEBUG, logger="clientwright.client.svc"):
        observation = emitter.call_start(INFO, started=0.0)
        emitter.call_end(observation, INFO, Outcome(kind=None, status_code=200), duration=0.1)

    # Fail closed: the raw URL is not published anywhere.
    assert tracer.spans[0].attributes["url.full"] == REDACTED
    assert all("alex@example.com" not in str(getattr(record, "url", "")) for record in caplog.records)
    assert tracer.spans[0].ended


def test__masker_raises__warns_once_per_client_not_per_call(caplog: pytest.LogCaptureFixture) -> None:
    def broken(value: str) -> str:
        raise RuntimeError("boom")

    emitter = telemetry(ObservabilityConfig(url_masker=broken))
    with caplog.at_level(logging.WARNING, logger="clientwright.client.svc"):
        for _ in range(3):
            observation = emitter.call_start(INFO, started=0.0)
            emitter.call_end(observation, INFO, Outcome(kind=None, status_code=200), duration=0.1)
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "url_masker" in warnings[0].getMessage()


# --- config validation ---


def test__url_masker_not_callable__rejected_at_config_time() -> None:
    with pytest.raises(ValueError, match="url_masker must be callable"):
        ObservabilityConfig(url_masker="not-a-callable")  # type: ignore[arg-type]
