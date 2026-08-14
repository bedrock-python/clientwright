"""Circuit breaker registry: monotonic clock, LRU-capped keys, thread-safe.

One signal per logical call: the engine calls ``check`` once before the attempt
loop and ``record`` once with the final outcome, so retries cannot pump the
failure counter of a single call. A call that dies without a classified outcome
(cancellation, adapter fault) is ``record_aborted`` - it releases its half-open
slot but is neither a success nor a failure signal.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from ..config import CircuitBreakerConfig
from ..errors import CircuitOpenError
from ..model import FailureKind, Outcome

logger = logging.getLogger("clientwright.circuit")


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(slots=True)
class _KeyState:
    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    opened_at: float = 0.0
    half_open_in_flight: int = 0

    @property
    def evictable(self) -> bool:
        """Only cold, fully closed circuits may be LRU-evicted."""
        return self.state is CircuitState.CLOSED and self.failures == 0 and self.half_open_in_flight == 0


StateListener = Callable[[str, CircuitState], None]


@dataclass(frozen=True, slots=True)
class CircuitSnapshot:
    state: CircuitState
    failures: int


class CircuitRegistry:
    """Per-key circuit state machines behind one lock (operations are O(1)).

    The state listener is invoked AFTER the lock is released, so a slow or
    re-entrant listener (one that calls ``snapshot()`` or triggers another
    call on a shared runtime) can neither stall other callers nor deadlock.
    """

    def __init__(
        self,
        config: CircuitBreakerConfig,
        clock: Callable[[], float],
        on_state_change: StateListener | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        self._on_state_change = on_state_change
        self._states: OrderedDict[str, _KeyState] = OrderedDict()
        self._lock = threading.Lock()

    def _get(self, key: str) -> _KeyState:
        state = self._states.pop(key, None)
        if state is None:
            state = _KeyState()
        self._states[key] = state
        if len(self._states) > self._config.max_keys:
            # Evict the least recently used COLD entry; an OPEN or HALF_OPEN
            # circuit must never be silently disarmed, so the cap is soft when
            # every entry is hot.
            for candidate_key, candidate in self._states.items():
                if candidate_key != key and candidate.evictable:
                    del self._states[candidate_key]
                    break
        return state

    def _notify(self, transitions: list[tuple[str, CircuitState]]) -> None:
        if self._on_state_change is None:
            return
        for key, state in transitions:
            try:
                self._on_state_change(key, state)
            except Exception:
                logger.debug("Circuit state listener failed for %s", key, exc_info=True)

    def check(self, key: str) -> None:
        """Admit or reject the logical call; may transition OPEN -> HALF_OPEN.

        The call that performs the transition consumes one half-open slot, so at
        most ``half_open_max_calls`` trial calls are in flight (the legacy kit
        let the transitioning call fly for free).
        """
        config = self._config
        transitions: list[tuple[str, CircuitState]] = []
        try:
            with self._lock:
                state = self._get(key)
                if state.state is CircuitState.OPEN:
                    elapsed = self._clock() - state.opened_at
                    if elapsed < config.recovery_timeout:
                        raise CircuitOpenError(key, retry_after=config.recovery_timeout - elapsed)
                    state.state = CircuitState.HALF_OPEN
                    state.half_open_in_flight = 0
                    transitions.append((key, CircuitState.HALF_OPEN))
                if state.state is CircuitState.HALF_OPEN:
                    if state.half_open_in_flight >= config.half_open_max_calls:
                        raise CircuitOpenError(key)
                    state.half_open_in_flight += 1
        finally:
            self._notify(transitions)

    def _trips(self, outcome: Outcome) -> bool:
        kind = outcome.kind
        if kind is None or kind not in self._config.trip_kinds:
            return False
        if kind is FailureKind.STATUS:
            return outcome.status_code is not None and outcome.status_code >= 500
        return True

    def record(self, key: str, outcome: Outcome) -> None:
        """Record the FINAL outcome of one admitted logical call."""
        config = self._config
        transitions: list[tuple[str, CircuitState]] = []
        with self._lock:
            state = self._get(key)
            if state.state is CircuitState.HALF_OPEN and state.half_open_in_flight > 0:
                state.half_open_in_flight -= 1
            if self._trips(outcome):
                state.failures += 1
                if state.state is CircuitState.HALF_OPEN or (
                    state.state is CircuitState.CLOSED and state.failures >= config.fail_threshold
                ):
                    state.state = CircuitState.OPEN
                    state.opened_at = self._clock()
                    state.half_open_in_flight = 0
                    transitions.append((key, CircuitState.OPEN))
            else:
                if state.state is CircuitState.HALF_OPEN:
                    state.state = CircuitState.CLOSED
                    transitions.append((key, CircuitState.CLOSED))
                state.failures = 0
        self._notify(transitions)

    def record_aborted(self, key: str) -> None:
        """An admitted call died without a classified outcome (cancellation,
        adapter fault): release its half-open slot, count nothing."""
        with self._lock:
            state = self._get(key)
            if state.state is CircuitState.HALF_OPEN and state.half_open_in_flight > 0:
                state.half_open_in_flight -= 1

    def snapshot(self) -> dict[str, CircuitSnapshot]:
        with self._lock:
            return {key: CircuitSnapshot(state=s.state, failures=s.failures) for key, s in self._states.items()}


__all__ = ["CircuitRegistry", "CircuitSnapshot", "CircuitState"]
