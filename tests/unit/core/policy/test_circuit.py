"""Circuit breaker state machine on a manual clock."""

from __future__ import annotations

import pytest

from clientwright.core.config import CircuitBreakerConfig
from clientwright.core.errors import CircuitOpenError
from clientwright.core.model import FailureKind, Outcome
from clientwright.core.policy.circuit import CircuitRegistry, CircuitState
from clientwright.core.testing import ManualClock

FAIL = Outcome(kind=FailureKind.CONNECT_TIMEOUT)
OK = Outcome(kind=None, status_code=200)
KEY = "https://a:443"


def registry(clock: ManualClock, **overrides: object) -> CircuitRegistry:
    config = CircuitBreakerConfig(fail_threshold=2, recovery_timeout=10.0, **overrides)  # type: ignore[arg-type]
    return CircuitRegistry(config, clock)


# --- state machine ---


def test__failures_below_threshold__stays_closed() -> None:
    clock = ManualClock()
    circuits = registry(clock)
    circuits.check(KEY)
    circuits.record(KEY, FAIL)
    circuits.check(KEY)  # still admitted


def test__threshold_reached__opens_and_rejects_with_retry_after() -> None:
    clock = ManualClock()
    circuits = registry(clock)
    for _ in range(2):
        circuits.check(KEY)
        circuits.record(KEY, FAIL)
    with pytest.raises(CircuitOpenError) as excinfo:
        circuits.check(KEY)
    assert excinfo.value.retry_after == pytest.approx(10.0)


def test__recovery__transitioning_call_consumes_half_open_slot() -> None:
    clock = ManualClock()
    circuits = registry(clock)
    for _ in range(2):
        circuits.check(KEY)
        circuits.record(KEY, FAIL)
    clock.advance(11.0)
    circuits.check(KEY)  # OPEN -> HALF_OPEN, consumes the only slot
    with pytest.raises(CircuitOpenError):
        circuits.check(KEY)  # the legacy kit let this one fly for free


def test__half_open_success__closes() -> None:
    clock = ManualClock()
    circuits = registry(clock)
    for _ in range(2):
        circuits.check(KEY)
        circuits.record(KEY, FAIL)
    clock.advance(11.0)
    circuits.check(KEY)
    circuits.record(KEY, OK)
    assert circuits.snapshot()[KEY].state is CircuitState.CLOSED
    circuits.check(KEY)


def test__half_open_failure__reopens() -> None:
    clock = ManualClock()
    circuits = registry(clock)
    for _ in range(2):
        circuits.check(KEY)
        circuits.record(KEY, FAIL)
    clock.advance(11.0)
    circuits.check(KEY)
    circuits.record(KEY, FAIL)
    with pytest.raises(CircuitOpenError):
        circuits.check(KEY)


def test__success__resets_failure_count() -> None:
    clock = ManualClock()
    circuits = registry(clock)
    circuits.check(KEY)
    circuits.record(KEY, FAIL)
    circuits.check(KEY)
    circuits.record(KEY, OK)
    circuits.check(KEY)
    circuits.record(KEY, FAIL)
    circuits.check(KEY)  # count restarted, still closed


# --- trip semantics ---


def test__5xx_trips_but_4xx_does_not() -> None:
    clock = ManualClock()
    circuits = registry(clock)
    for _ in range(2):
        circuits.check(KEY)
        circuits.record(KEY, Outcome(kind=FailureKind.STATUS, status_code=503))
    with pytest.raises(CircuitOpenError):
        circuits.check(KEY)
    other = registry(clock)
    for _ in range(3):
        other.check(KEY)
        other.record(KEY, Outcome(kind=None, status_code=404))
    other.check(KEY)


def test__kind_outside_trip_set__does_not_trip() -> None:
    clock = ManualClock()
    circuits = registry(clock)
    for _ in range(3):
        circuits.check(KEY)
        circuits.record(KEY, Outcome(kind=FailureKind.CANCELLED))
    circuits.check(KEY)


# --- aborted calls ---


def test__aborted_half_open_probe__keeps_half_open_and_frees_slot() -> None:
    clock = ManualClock()
    circuits = registry(clock)
    for _ in range(2):
        circuits.check(KEY)
        circuits.record(KEY, FAIL)
    clock.advance(11.0)
    circuits.check(KEY)  # HALF_OPEN, slot consumed
    circuits.record_aborted(KEY)  # probe cancelled: neither success nor failure
    assert circuits.snapshot()[KEY].state is CircuitState.HALF_OPEN
    circuits.check(KEY)  # slot was released, next probe admitted


def test__aborted_call__does_not_reset_failure_count() -> None:
    clock = ManualClock()
    circuits = registry(clock)
    circuits.check(KEY)
    circuits.record(KEY, FAIL)
    circuits.check(KEY)
    circuits.record_aborted(KEY)
    circuits.check(KEY)
    circuits.record(KEY, FAIL)  # second real failure reaches threshold 2
    with pytest.raises(CircuitOpenError):
        circuits.check(KEY)


# --- registry mechanics ---


def test__lru__evicts_oldest_cold_key() -> None:
    clock = ManualClock()
    circuits = registry(clock, max_keys=2)
    for key in ("a", "b", "c"):
        circuits.check(key)
    snapshot = circuits.snapshot()
    assert set(snapshot) == {"b", "c"}


def test__lru__never_evicts_open_circuit() -> None:
    clock = ManualClock()
    circuits = registry(clock, max_keys=2)
    for _ in range(2):
        circuits.check("hot")
        circuits.record("hot", FAIL)  # "hot" is now OPEN
    for key in ("x", "y", "z"):
        circuits.check(key)
    assert "hot" in circuits.snapshot()  # an armed breaker is not silently disarmed
    with pytest.raises(CircuitOpenError):
        circuits.check("hot")


def test__listener__may_reenter_registry_without_deadlock() -> None:
    clock = ManualClock()
    seen: list[str] = []

    def listener(key: str, state: CircuitState) -> None:
        # A listener that logs the whole snapshot is ordinary usage; it must
        # not deadlock on the registry's internal lock.
        seen.append(f"{key}={state.value} snapshot={len(circuits.snapshot())}")

    config = CircuitBreakerConfig(fail_threshold=1, recovery_timeout=10.0)
    circuits = CircuitRegistry(config, clock, listener)
    circuits.check(KEY)
    circuits.record(KEY, FAIL)
    assert seen  # transition observed, no deadlock


def test__raising_listener__swallowed_without_breaking_the_call() -> None:
    clock = ManualClock()

    def bad_listener(key: str, state: CircuitState) -> None:
        raise RuntimeError("listener exploded")

    config = CircuitBreakerConfig(fail_threshold=1, recovery_timeout=10.0)
    circuits = CircuitRegistry(config, clock, bad_listener)
    circuits.check(KEY)
    circuits.record(KEY, FAIL)  # OPEN transition notifies the listener; its crash must not surface
    assert circuits.snapshot()[KEY].state is CircuitState.OPEN


def test__listener__notified_on_transitions() -> None:
    clock = ManualClock()
    seen: list[tuple[str, CircuitState]] = []
    config = CircuitBreakerConfig(fail_threshold=1, recovery_timeout=10.0)
    circuits = CircuitRegistry(config, clock, lambda key, state: seen.append((key, state)))
    circuits.check(KEY)
    circuits.record(KEY, FAIL)
    clock.advance(11.0)
    circuits.check(KEY)
    circuits.record(KEY, OK)
    assert [state for _, state in seen] == [CircuitState.OPEN, CircuitState.HALF_OPEN, CircuitState.CLOSED]
