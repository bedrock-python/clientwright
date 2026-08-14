"""ClientTelemetry - the single emitter driving logs, metrics and spans.

Observability closes in ``finally`` for every path: an attempt that dies with
an exception still decrements in-flight, ends its span and records metrics -
the legacy kit's event hooks lost every exception outcome.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import ObservabilityConfig
from ..contracts.observability import ClientMetricsProtocol, SpanProtocol, TracerProtocol
from ..model import Attempt, Outcome, RequestInfo
from .names import OUTCOME_SUCCESS, ROUTE_UNKNOWN, STATUS_NONE
from .null import NullMetrics, NullTracer
from .redaction import REDACTED, redact_url


def outcome_label(outcome: Outcome) -> str:
    return OUTCOME_SUCCESS if outcome.kind is None else outcome.kind.value


def status_label(outcome: Outcome) -> str:
    return STATUS_NONE if outcome.status_code is None else str(outcome.status_code)


@dataclass(slots=True)
class CallObservation:
    """Mutable per-call observation state carried through the engine."""

    span: SpanProtocol
    started: float
    hops: int = 0
    attempts: int = 0


class ClientTelemetry:
    """One instance per built client; adapter/seam are burned in as constants."""

    def __init__(
        self,
        *,
        service: str,
        adapter: str,
        seam: str,
        config: ObservabilityConfig,
        metrics: ClientMetricsProtocol | None,
        tracer: TracerProtocol | None,
    ) -> None:
        self._service = service
        self._adapter = adapter
        self._seam = seam
        self._config = config
        self._metrics: ClientMetricsProtocol = metrics if (metrics and config.metrics) else NullMetrics()
        self._tracer: TracerProtocol = tracer if (tracer and config.tracing) else NullTracer()
        self._logger = logging.getLogger(f"clientwright.client.{service}")
        self._log_enabled = config.logging
        self._masker_warned = False

    @property
    def tracer(self) -> TracerProtocol:
        return self._tracer

    def _safe_url(self, info: RequestInfo) -> str:
        url = redact_url(info.url, self._config.sensitive_query_params)
        masker = self._config.url_masker
        if masker is None:
            return url
        # Fail closed: a broken masker must not publish the raw URL, and must
        # not break the request either. Warn once per client, not per call.
        try:
            return masker(url)
        except Exception:
            if not self._masker_warned:
                self._masker_warned = True
                self._logger.warning("url_masker raised; emitting [redacted] instead of the URL", exc_info=True)
            return REDACTED

    def call_start(self, info: RequestInfo, started: float) -> CallObservation:
        span = self._tracer.start_span(
            f"HTTP {info.method}",
            attributes={
                "http.request.method": info.method,
                "server.origin": info.origin,
                "url.full": self._safe_url(info),
            },
        )
        self._metrics.inflight_delta(
            service=self._service, adapter=self._adapter, seam=self._seam, origin=info.origin, delta=1
        )
        if self._log_enabled:
            self._logger.debug(
                "HTTP call started",
                extra={"method": info.method, "url": self._safe_url(info), "origin": info.origin},
            )
        return CallObservation(span=span, started=started)

    def attempt_end(self, info: RequestInfo, attempt: Attempt) -> None:
        self._metrics.record_attempt(
            service=self._service,
            adapter=self._adapter,
            seam=self._seam,
            method=info.method,
            origin=info.origin,
            outcome=outcome_label(attempt.outcome),
            duration=attempt.duration,
        )

    def redirect_hop(self, observation: CallObservation) -> None:
        observation.hops += 1
        self._metrics.record_redirect_hop(service=self._service, adapter=self._adapter, seam=self._seam)

    def retry_skipped(self, reason: str) -> None:
        self._metrics.record_retry_skipped(service=self._service, adapter=self._adapter, seam=self._seam, reason=reason)

    def circuit_state_changed(self, key: str, state: str) -> None:
        self._metrics.record_circuit_state(service=self._service, adapter=self._adapter, key=key, state=state)

    def uninstrumented_call(self) -> None:
        """A call bypassed the instrumentation seam (e.g. aiohttp middlewares=())."""
        self._metrics.record_uninstrumented_call(service=self._service, adapter=self._adapter, seam=self._seam)

    def call_end(self, observation: CallObservation, info: RequestInfo, outcome: Outcome, duration: float) -> None:
        route = info.route or ROUTE_UNKNOWN
        try:
            self._metrics.record_call(
                service=self._service,
                adapter=self._adapter,
                seam=self._seam,
                method=info.method,
                origin=info.origin,
                route=route,
                status=status_label(outcome),
                outcome=outcome_label(outcome),
                duration=duration,
            )
            self._metrics.inflight_delta(
                service=self._service, adapter=self._adapter, seam=self._seam, origin=info.origin, delta=-1
            )
            if self._log_enabled:
                extra = {
                    "method": info.method,
                    "url": self._safe_url(info),
                    "origin": info.origin,
                    "outcome": outcome_label(outcome),
                    "status": status_label(outcome),
                    "duration": round(duration, 6),
                    "attempts": observation.attempts,
                    "hops": observation.hops,
                }
                if outcome.kind is None:
                    self._logger.log(self._config.success_log_level, "HTTP call finished", extra=extra)
                else:
                    self._logger.warning("HTTP call failed", extra=extra)
        finally:
            if outcome.status_code is not None:
                observation.span.set_attribute("http.response.status_code", outcome.status_code)
            if outcome.kind is not None:
                observation.span.record_failure(outcome_label(outcome))
            observation.span.end()

    def record_body_duration(self, info: RequestInfo, duration: float) -> None:
        self._metrics.record_body_duration(
            service=self._service,
            adapter=self._adapter,
            seam=self._seam,
            method=info.method,
            origin=info.origin,
            route=info.route or ROUTE_UNKNOWN,
            duration=duration,
        )


__all__ = ["CallObservation", "ClientTelemetry", "outcome_label", "status_label"]
