"""Per-attempt timeout planning.

The planner starts from base phases (config knobs already resolved against the
adapter's native defaults at build time), merges the caller's per-call override
according to ``CallerOverride``, then clamps every phase and the attempt
ceiling by the remaining total budget.
"""

from __future__ import annotations

from ..config import CallerOverride, TimeoutConfig, resolve
from ..errors import CallError
from ..model import ResolvedTimeouts


class CallerOverrideForbiddenError(CallError):
    def __init__(self) -> None:
        super().__init__("Per-call timeout overrides are forbidden by config (caller_override=raise)")


def base_timeouts(config: TimeoutConfig, native_defaults: ResolvedTimeouts) -> ResolvedTimeouts:
    """Resolve UNSET phases against the adapter's native defaults, once, at build."""
    return ResolvedTimeouts(
        connect=resolve(config.connect, native_defaults.connect),
        read=resolve(config.read, native_defaults.read),
        write=resolve(config.write, native_defaults.write),
        pool_acquire=resolve(config.pool_acquire, native_defaults.pool_acquire),
        attempt=resolve(config.attempt, None),
    )


class TimeoutPlanner:
    __slots__ = ("_base", "_caller_override")

    def __init__(self, base: ResolvedTimeouts, caller_override: CallerOverride) -> None:
        self._base = base
        self._caller_override = caller_override

    @staticmethod
    def _clamp(phase: float | None, remaining: float | None) -> float | None:
        if remaining is None:
            return phase
        if phase is None:
            return remaining
        return min(phase, remaining)

    def plan(self, *, remaining: float | None, caller: ResolvedTimeouts | None) -> ResolvedTimeouts:
        base = self._base
        if caller is not None:
            if self._caller_override is CallerOverride.RAISE:
                raise CallerOverrideForbiddenError
            if self._caller_override is CallerOverride.CALLER_WINS:
                base = caller
        attempt = self._clamp(base.attempt, remaining)
        return ResolvedTimeouts(
            connect=self._clamp(base.connect, remaining),
            read=self._clamp(base.read, remaining),
            write=self._clamp(base.write, remaining),
            pool_acquire=self._clamp(base.pool_acquire, remaining),
            attempt=attempt,
        )


__all__ = ["CallerOverrideForbiddenError", "TimeoutPlanner", "base_timeouts"]
