"""Budget propagation semantics of the ambient channel: tasks inherit, threads do not."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from clientwright.contrib.deadline import DeadlineBudgetProtocol, current_budget, use_budget


class FakeBudget:
    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    def remaining(self) -> float:
        return self._seconds

    def expired(self) -> bool:
        return self._seconds <= 0


async def test__task_started_inside_the_block__inherits_the_budget() -> None:
    async def read_ambient() -> DeadlineBudgetProtocol | None:
        return current_budget()

    budget = FakeBudget(5.0)
    with use_budget(budget):
        inside = asyncio.create_task(read_ambient())
        assert await inside is budget  # a fan-out started under the budget shares its deadline
    outside = asyncio.create_task(read_ambient())
    assert await outside is None  # a sibling started after the block does not


async def test__detached_child__escapes_the_request_budget() -> None:
    async def read_ambient() -> DeadlineBudgetProtocol | None:
        return current_budget()

    with use_budget(FakeBudget(5.0)), use_budget(None):
        background = asyncio.create_task(read_ambient())
        assert await background is None  # background work must not die with the request


def test__other_threads__never_see_this_threads_budget() -> None:
    with use_budget(FakeBudget(5.0)), ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(current_budget).result() is None


def test__protocol__is_runtime_checkable() -> None:
    assert isinstance(FakeBudget(1.0), DeadlineBudgetProtocol)
    assert not isinstance(object(), DeadlineBudgetProtocol)
