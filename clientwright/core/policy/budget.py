"""Monotonic deadlines and per-origin retry budgets."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable


class Deadline:
    """Wall-of-time budget of one logical call, measured on a monotonic clock."""

    __slots__ = ("_clock", "_expires_at", "total")

    def __init__(self, total: float | None, clock: Callable[[], float]) -> None:
        self.total = total
        self._clock = clock
        self._expires_at = None if total is None else clock() + total

    @classmethod
    def intersect(cls, clock: Callable[[], float], *totals: float | None) -> Deadline:
        """The tightest of several budgets; ``None`` entries do not constrain."""
        bounded = [total for total in totals if total is not None]
        return cls(min(bounded) if bounded else None, clock)

    def remaining(self) -> float | None:
        if self._expires_at is None:
            return None
        return self._expires_at - self._clock()

    @property
    def expired(self) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining <= 0


class RetryBudgetRegistry:
    """Token-bucket retry budget per origin.

    Every logical call earns ``ratio`` tokens; every retry spends one. With the
    default ratio of 0.1 at most ~10% of traffic can be retries, which prevents
    retry storms against a struggling upstream.
    """

    _MAX_TOKENS = 10.0

    def __init__(self, ratio: float | None, max_origins: int = 512) -> None:
        self._ratio = ratio
        self._max_origins = max_origins
        self._tokens: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def earn(self, origin: str) -> None:
        if self._ratio is None:
            return
        with self._lock:
            tokens = self._tokens.pop(origin, None)
            # A fresh origin starts with a FULL bucket: an initial burst of
            # retries is allowed, the sustained rate is capped by the ratio.
            self._tokens[origin] = self._MAX_TOKENS if tokens is None else min(tokens + self._ratio, self._MAX_TOKENS)
            while len(self._tokens) > self._max_origins:
                self._tokens.popitem(last=False)

    def try_spend(self, origin: str) -> bool:
        if self._ratio is None:
            return True
        with self._lock:
            tokens = self._tokens.get(origin, 0.0)
            if tokens < 1.0:
                return False
            self._tokens[origin] = tokens - 1.0
            self._tokens.move_to_end(origin)
            return True


__all__ = ["Deadline", "RetryBudgetRegistry"]
