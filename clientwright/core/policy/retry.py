"""Retry decision policy: a pure function shared by the sync and async engines.

``decide`` never sleeps, never logs and knows nothing about coroutines; the
engine owns the loop, the sleeping and the budget accounting.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from random import Random

from ..config import RetryConfig
from ..model import Attempt, FailureKind, RequestInfo

# A retry whose backoff would land this close to the deadline is pointless.
_DEADLINE_SLACK = 0.001


@dataclass(frozen=True, slots=True)
class RetryDecision:
    retry: bool
    delay: float = 0.0
    reason: str = ""


class DefaultRetryPolicy:
    """Config-driven policy implementing the org-wide retry semantics."""

    def __init__(self, config: RetryConfig) -> None:
        self._config = config

    def _wants_retry(self, attempt: Attempt) -> str | None:
        """Reason string when the last outcome is retry-worthy, else None."""
        outcome = attempt.outcome
        if outcome.status_code is not None and outcome.status_code in self._config.retryable_status:
            return f"status_{outcome.status_code}"
        kind = outcome.kind
        if kind is not None and kind is not FailureKind.STATUS and kind in self._config.retryable_kinds:
            return f"kind_{kind.value}"
        return None

    def _backoff(self, attempt_index: int, retry_after: float | None, rng: Random) -> float:
        config = self._config
        if config.respect_retry_after and retry_after is not None:
            return min(retry_after, config.retry_after_max)
        delay = min(config.initial_backoff * config.multiplier ** (attempt_index - 1), config.max_backoff)
        if config.jitter:
            delay *= 1.0 + rng.uniform(-config.jitter, config.jitter)
        return max(delay, 0.0)

    def decide(
        self,
        *,
        info: RequestInfo,
        history: Sequence[Attempt],
        remaining: float | None,
        replayable: bool,
        rng: Random,
    ) -> RetryDecision:
        if not history:
            return RetryDecision(retry=False, reason="no_attempts")
        config = self._config
        last = history[-1]
        reason = self._wants_retry(last)
        if reason is None:
            return RetryDecision(retry=False, reason="final")
        if len(history) >= config.max_attempts:
            return RetryDecision(retry=False, reason="attempts")
        if info.method not in config.methods and not info.idempotent:
            return RetryDecision(retry=False, reason="method")
        if config.require_replayable_body and not replayable:
            return RetryDecision(retry=False, reason="non_replayable")
        delay = self._backoff(len(history), last.outcome.retry_after, rng)
        if remaining is not None and delay + _DEADLINE_SLACK >= remaining:
            return RetryDecision(retry=False, reason="deadline")
        return RetryDecision(retry=True, delay=delay, reason=reason)


__all__ = ["DefaultRetryPolicy", "RetryDecision"]
