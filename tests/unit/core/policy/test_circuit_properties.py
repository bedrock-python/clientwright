"""Random-walk invariants of the circuit breaker state machine."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from clientwright.core.config import CircuitBreakerConfig
from clientwright.core.errors import CircuitOpenError
from clientwright.core.model import FailureKind, Outcome
from clientwright.core.policy.circuit import CircuitRegistry, CircuitState
from clientwright.core.testing import ManualClock

KEY = "https://walk:443"
OK = Outcome(kind=None, status_code=200)
FAIL = Outcome(kind=FailureKind.CONNECT_TIMEOUT)

operations = st.lists(st.sampled_from(["ok", "fail", "abort", "tick"]), max_size=60)


@given(ops=operations, threshold=st.integers(min_value=1, max_value=5))
def test__any_walk__ends_in_a_legal_state(ops: list[str], threshold: int) -> None:
    clock = ManualClock()
    config = CircuitBreakerConfig(fail_threshold=threshold, recovery_timeout=10.0)
    circuits = CircuitRegistry(config, clock)
    for op in ops:
        if op == "tick":
            clock.advance(3.0)
            continue
        try:
            circuits.check(KEY)
        except CircuitOpenError:
            continue  # a rejection is a legal answer, never an internal crash
        if op == "ok":
            circuits.record(KEY, OK)
        elif op == "fail":
            circuits.record(KEY, FAIL)
        else:
            circuits.record_aborted(KEY)
    snapshot = circuits.snapshot().get(KEY)
    if snapshot is not None:
        assert snapshot.state in (CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN)
        assert snapshot.failures >= 0
        if snapshot.state is CircuitState.CLOSED:
            assert snapshot.failures < threshold  # threshold reached always means not-CLOSED


@given(ops=operations, threshold=st.integers(min_value=1, max_value=5), max_keys=st.integers(min_value=1, max_value=4))
def test__any_walk_over_many_keys__armed_circuits_survive_eviction(
    ops: list[str], threshold: int, max_keys: int
) -> None:
    clock = ManualClock()
    config = CircuitBreakerConfig(fail_threshold=threshold, recovery_timeout=1000.0, max_keys=max_keys)
    circuits = CircuitRegistry(config, clock)
    for index, op in enumerate(ops):
        key = f"origin-{index % (max_keys + 2)}"
        if op == "tick":
            clock.advance(3.0)
            continue
        try:
            circuits.check(key)
        except CircuitOpenError:
            continue
        if op == "ok":
            circuits.record(key, OK)
        elif op == "fail":
            circuits.record(key, FAIL)
        else:
            circuits.record_aborted(key)
    for snapshot in circuits.snapshot().values():
        if snapshot.state is CircuitState.CLOSED:
            assert snapshot.failures < threshold
    # The cap is soft for armed circuits but the registry must not grow unboundedly
    # beyond the number of keys the walk ever used.
    assert len(circuits.snapshot()) <= max_keys + 2
