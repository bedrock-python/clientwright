"""deadline-budget integration (``[deadline]`` extra).

The core stays zero-dependency: the engine consumes the structural
``DeadlineSource`` protocol, and this module supplies sources backed by a
deadline-budget ``BudgetContext`` - plus the ambient channel that carries one.

deadline-budget deliberately has no implicit context: a ``BudgetContext`` is
handed from call site to call site by argument. A client engine sits far below
the code that knows the budget, so the ambient channel lives here::

    from clientwright.contrib.deadline import AmbientDeadlineSource, use_budget

    deps = AdapterDeps(deadline_source=AmbientDeadlineSource())
    client = build("httpx", config, deps)

    with use_budget(BudgetContext.create(total_seconds=5.0)):
        await client.get("/users")  # runs with what is left of those 5 seconds

Without the block every call behaves exactly as before: the ambient source
finds no budget and the engine falls back to the configured total.

Typed structurally on purpose - this module never imports deadline-budget, so
any object with ``remaining()``/``expired()`` fits; the ``[deadline]`` extra
exists to pin the library for services that use the real one. A ContextVar is
per-task: a task started under ``use_budget`` inherits the budget (a fan-out
shares one deadline), siblings do not.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Protocol, runtime_checkable


@runtime_checkable
class DeadlineBudgetProtocol(Protocol):
    """What a source needs of a request budget: the shape of ``deadline_budget.BudgetContext``."""

    def remaining(self) -> float:
        """Seconds left; negative once the deadline has passed."""
        ...

    def expired(self) -> bool: ...


_CURRENT_BUDGET: ContextVar[DeadlineBudgetProtocol | None] = ContextVar("clientwright_budget", default=None)


def current_budget() -> DeadlineBudgetProtocol | None:
    """The budget installed for the current task, or None if there is none."""
    return _CURRENT_BUDGET.get()


@contextmanager
def use_budget(budget: DeadlineBudgetProtocol | None) -> Generator[DeadlineBudgetProtocol | None]:
    """Install ``budget`` as the current one for the duration of the block.

    The previous value is restored on the way out, so nesting works and an
    inner budget cannot outlive its block. Passing None detaches an inherited
    budget - for background work that must not die with the request that
    spawned it.
    """
    token: Token[DeadlineBudgetProtocol | None] = _CURRENT_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _CURRENT_BUDGET.reset(token)


class BudgetDeadlineSource:
    """DeadlineSource over ONE fixed budget - for a client scoped to a request."""

    __slots__ = ("_budget",)

    def __init__(self, budget: DeadlineBudgetProtocol) -> None:
        self._budget = budget

    def remaining(self) -> float | None:
        return self._budget.remaining()


class AmbientDeadlineSource:
    """DeadlineSource reading whatever ``use_budget`` installed in this task.

    The right default for a long-lived client: each call picks up the budget
    of the request being served, and calls outside any budget run unbounded
    by it (only the configured total applies).
    """

    __slots__ = ()

    def remaining(self) -> float | None:
        budget = current_budget()
        if budget is None:
            return None
        return budget.remaining()


__all__ = [
    "AmbientDeadlineSource",
    "BudgetDeadlineSource",
    "DeadlineBudgetProtocol",
    "current_budget",
    "use_budget",
]
