"""Response classification, Retry-After parsing and header helpers from the engine base."""

from __future__ import annotations

from clientwright.core.engine.base import (
    deadline_header_value,
    default_response_outcome,
    inject_static_headers,
    parse_retry_after,
)
from clientwright.core.model import FailureKind
from tests.helpers.views import FakeResponse

# --- classification ---


def test__200__success_outcome() -> None:
    outcome = default_response_outcome(FakeResponse(200))
    assert outcome.ok
    assert outcome.status_code == 200


def test__500__status_failure() -> None:
    outcome = default_response_outcome(FakeResponse(500))
    assert outcome.kind is FailureKind.STATUS


def test__429_with_retry_after__captured() -> None:
    outcome = default_response_outcome(FakeResponse(429, {"Retry-After": "7"}))
    assert outcome.ok  # 4xx is not an infrastructure failure
    assert outcome.retry_after == 7.0


def test__retry_after__parses_digits_dates_and_garbage() -> None:
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0  # in the past -> floor 0
    assert parse_retry_after("nonsense") is None
    assert parse_retry_after(None) is None


# --- header helpers ---


def test__inject_static_headers__setdefault_semantics() -> None:
    headers = {"x-set-by-caller": "caller"}
    inject_static_headers(headers, {"x-set-by-caller": "config", "x-new": "config"})
    assert headers == {"x-set-by-caller": "caller", "x-new": "config"}


def test__deadline_header_value__whole_milliseconds_floored_at_zero() -> None:
    assert deadline_header_value(1.5) == "1500"
    assert deadline_header_value(0.0004) == "0"
    assert deadline_header_value(-3.0) == "0"
