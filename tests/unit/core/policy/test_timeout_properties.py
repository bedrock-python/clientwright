"""Property invariants of per-attempt timeout planning."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from clientwright.core.config import CallerOverride
from clientwright.core.model import ResolvedTimeouts
from clientwright.core.policy.timeout import TimeoutPlanner

phase_values = st.none() | st.floats(min_value=0.001, max_value=120.0, allow_nan=False, allow_infinity=False)

resolved_timeouts = st.builds(
    ResolvedTimeouts,
    connect=phase_values,
    read=phase_values,
    write=phase_values,
    pool_acquire=phase_values,
    attempt=phase_values,
)

PHASES = ("connect", "read", "write", "pool_acquire", "attempt")


@given(
    base=resolved_timeouts,
    caller=st.none() | resolved_timeouts,
    remaining=st.floats(min_value=0.001, max_value=60.0, allow_nan=False),
)
def test__every_planned_phase__clamped_by_the_remaining_budget(
    base: ResolvedTimeouts, caller: ResolvedTimeouts | None, remaining: float
) -> None:
    planner = TimeoutPlanner(base, CallerOverride.CALLER_WINS)
    plan = planner.plan(remaining=remaining, caller=caller)
    for phase in PHASES:
        value = getattr(plan, phase)
        if value is not None:
            assert value <= remaining + 1e-9
            assert value > 0.0
    assert plan.attempt is not None  # a bounded call always has an attempt ceiling
    assert plan.attempt <= remaining + 1e-9


@given(base=resolved_timeouts, caller=resolved_timeouts)
def test__config_wins__caller_input_is_irrelevant(base: ResolvedTimeouts, caller: ResolvedTimeouts) -> None:
    planner = TimeoutPlanner(base, CallerOverride.CONFIG_WINS)
    with_caller = planner.plan(remaining=None, caller=caller)
    without_caller = planner.plan(remaining=None, caller=None)
    assert with_caller == without_caller


@given(base=resolved_timeouts)
def test__unbounded_call__base_passes_through_unchanged(base: ResolvedTimeouts) -> None:
    planner = TimeoutPlanner(base, CallerOverride.CALLER_WINS)
    plan = planner.plan(remaining=None, caller=None)
    for phase in ("connect", "read", "write", "pool_acquire"):
        assert getattr(plan, phase) == getattr(base, phase)
