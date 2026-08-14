"""contrib units: deadline-budget sources and the dishka provider."""

from __future__ import annotations

import pytest

from clientwright.contrib.deadline import (
    AmbientDeadlineSource,
    BudgetDeadlineSource,
    current_budget,
    use_budget,
)


class FakeBudget:
    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    def remaining(self) -> float:
        return self._seconds

    def expired(self) -> bool:
        return self._seconds <= 0


def test__ambient__none_without_budget() -> None:
    assert current_budget() is None
    assert AmbientDeadlineSource().remaining() is None


def test__use_budget__nests_and_restores() -> None:
    source = AmbientDeadlineSource()
    with use_budget(FakeBudget(5.0)):
        assert source.remaining() == 5.0
        with use_budget(FakeBudget(1.0)):
            assert source.remaining() == 1.0
        assert source.remaining() == 5.0
    assert source.remaining() is None


def test__use_budget_none__detaches_inherited_budget() -> None:
    source = AmbientDeadlineSource()
    with use_budget(FakeBudget(5.0)), use_budget(None):
        assert source.remaining() is None


def test__fixed_source__reads_its_budget() -> None:
    assert BudgetDeadlineSource(FakeBudget(2.5)).remaining() == 2.5


def test__real_deadline_budget__satisfies_the_protocol() -> None:
    deadline_budget = pytest.importorskip("deadline_budget", reason="requires the [deadline] extra")
    budget = deadline_budget.BudgetContext.create(total_seconds=5.0)
    with use_budget(budget):
        remaining = AmbientDeadlineSource().remaining()
    assert remaining is not None
    assert 0.0 < remaining <= 5.0
