"""Deadlines and retry budgets."""

from __future__ import annotations

import pytest

from clientwright.core.policy.budget import Deadline, RetryBudgetRegistry
from clientwright.core.testing import ManualClock

# --- Deadline ---


def test__remaining__shrinks_with_clock() -> None:
    clock = ManualClock()
    deadline = Deadline(10.0, clock)
    clock.advance(4.0)
    assert deadline.remaining() == pytest.approx(6.0)
    assert not deadline.expired
    clock.advance(7.0)
    assert deadline.expired


def test__unbounded__never_expires() -> None:
    deadline = Deadline(None, ManualClock())
    assert deadline.remaining() is None
    assert not deadline.expired


def test__intersect__takes_tightest_non_none() -> None:
    clock = ManualClock()
    assert Deadline.intersect(clock, 10.0, None, 3.0).total == 3.0
    assert Deadline.intersect(clock, None, None).total is None


# --- retry budget ---


def test__fresh_origin__starts_with_full_bucket() -> None:
    budget = RetryBudgetRegistry(ratio=0.1)
    budget.earn("o")
    assert budget.try_spend("o")


def test__exhausted_bucket__denies_until_earned_back() -> None:
    budget = RetryBudgetRegistry(ratio=0.5)
    budget.earn("o")
    for _ in range(10):
        assert budget.try_spend("o")
    assert not budget.try_spend("o")
    budget.earn("o")
    assert not budget.try_spend("o")  # 0.5 tokens is still below 1
    budget.earn("o")
    assert budget.try_spend("o")


def test__none_ratio__always_allows() -> None:
    budget = RetryBudgetRegistry(ratio=None)
    assert budget.try_spend("anything")
