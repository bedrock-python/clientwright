"""Per-attempt timeout planning and caller-override modes."""

from __future__ import annotations

import pytest

from clientwright.core.config import UNSET, CallerOverride, TimeoutConfig
from clientwright.core.model import ResolvedTimeouts
from clientwright.core.policy.timeout import CallerOverrideForbiddenError, TimeoutPlanner, base_timeouts

# --- base_timeouts ---


def test__unset_phases__fall_back_to_native_defaults() -> None:
    native = ResolvedTimeouts(connect=9.0, read=9.0, write=9.0, pool_acquire=9.0)
    base = base_timeouts(TimeoutConfig(total=30.0, connect=2.0, read=UNSET), native)
    assert base.connect == 2.0
    assert base.read == 9.0
    assert base.write == 9.0


# --- planner ---

PLANNER_BASE = ResolvedTimeouts(connect=2.0, read=5.0, write=5.0, pool_acquire=1.0)


def test__no_deadline__base_passes_through() -> None:
    planner = TimeoutPlanner(PLANNER_BASE, CallerOverride.CALLER_WINS)
    plan = planner.plan(remaining=None, caller=None)
    assert plan.connect == 2.0
    assert plan.read == 5.0
    assert plan.attempt is None


def test__remaining_budget__clamps_every_phase_and_attempt() -> None:
    planner = TimeoutPlanner(PLANNER_BASE, CallerOverride.CALLER_WINS)
    plan = planner.plan(remaining=1.5, caller=None)
    assert plan.connect == 1.5
    assert plan.read == 1.5
    assert plan.attempt == 1.5


def test__caller_wins__caller_phases_replace_but_stay_clamped() -> None:
    planner = TimeoutPlanner(PLANNER_BASE, CallerOverride.CALLER_WINS)
    caller = ResolvedTimeouts(connect=60.0, read=60.0)
    plan = planner.plan(remaining=3.0, caller=caller)
    assert plan.connect == 3.0
    assert plan.read == 3.0


def test__config_wins__caller_ignored() -> None:
    planner = TimeoutPlanner(PLANNER_BASE, CallerOverride.CONFIG_WINS)
    caller = ResolvedTimeouts(connect=60.0)
    plan = planner.plan(remaining=None, caller=caller)
    assert plan.connect == 2.0


def test__raise_mode__rejects_caller_override() -> None:
    planner = TimeoutPlanner(PLANNER_BASE, CallerOverride.RAISE)
    with pytest.raises(CallerOverrideForbiddenError):
        planner.plan(remaining=None, caller=ResolvedTimeouts(connect=1.0))
