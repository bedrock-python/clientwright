"""Pure helpers shared by the sync and async engines."""

from __future__ import annotations

import datetime
import email.utils
from collections.abc import MutableMapping

from ..contracts.message import ResponseView
from ..model import FailureKind, Outcome

# Statuses that commonly carry Retry-After.
_RETRY_AFTER_STATUSES = frozenset({413, 429, 503})

# Reasons worth a retry_skipped sentinel: the policy WANTED to retry but could not.
SKIP_REASONS = frozenset({"method", "non_replayable", "deadline", "budget"})


def parse_retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After header: integer form or HTTP-date form."""
    if not value:
        return None
    text = value.strip()
    if text.isdigit():
        return float(text)
    try:
        when = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.UTC)
    delta = (when - datetime.datetime.now(datetime.UTC)).total_seconds()
    return max(delta, 0.0)


def default_response_outcome(response: ResponseView) -> Outcome:
    """Default classification: a received response is a failure only when 5xx.

    Retry-After is captured for throttling and unavailability statuses so the
    retry policy can honor it.
    """
    status = response.status_code
    retry_after = parse_retry_after(response.header("retry-after")) if status in _RETRY_AFTER_STATUSES else None
    kind = FailureKind.STATUS if status >= 500 else None
    return Outcome(kind=kind, status_code=status, retry_after=retry_after)


def inject_static_headers(headers: MutableMapping[str, str], extra: dict[str, str]) -> None:
    """setdefault semantics: caller-set headers always win."""
    for name, value in extra.items():
        if name not in headers:
            headers[name] = value


def deadline_header_value(remaining: float) -> str:
    return str(max(int(remaining * 1000), 0))


__all__ = [
    "SKIP_REASONS",
    "deadline_header_value",
    "default_response_outcome",
    "inject_static_headers",
    "parse_retry_after",
]
