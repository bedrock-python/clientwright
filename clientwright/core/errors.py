"""Kernel error hierarchy.

Errors raised on the call path (``CallError`` subclasses) are translated by each
adapter into classes that ALSO inherit the native client's error family, so a
user's ``except httpx.HTTPError`` keeps working. Errors raised at build time are
plain kernel errors.
"""

from __future__ import annotations


class ClientwrightError(Exception):
    """Base class for everything clientwright raises on its own authority."""


class UnknownAdapterError(ClientwrightError):
    """Requested adapter name is not registered."""

    def __init__(self, name: str, known: tuple[str, ...]) -> None:
        super().__init__(f"Unknown adapter {name!r}; registered adapters: {', '.join(known) or '<none>'}")
        self.name = name
        self.known = known


class UnsupportedCapabilityError(ClientwrightError):
    """Config asks for something the chosen adapter cannot express (STRICT mode)."""


class NativeConfigError(ClientwrightError):
    """Base for invalid native passthrough configuration."""


class UnknownNativeSlotError(NativeConfigError):
    def __init__(self, slot: str, known: tuple[str, ...]) -> None:
        super().__init__(f"Unknown native slot {slot!r}; adapter slots: {', '.join(known)}")
        self.slot = slot
        self.known = known


class ReservedNativeKeyError(NativeConfigError):
    def __init__(self, slot: str, key: str, hint: str) -> None:
        super().__init__(f"Native key {key!r} in slot {slot!r} is owned by clientwright: {hint}")
        self.slot = slot
        self.key = key


class UnknownNativeKeyError(NativeConfigError):
    def __init__(self, slot: str, key: str, suggestion: str | None = None) -> None:
        hint = f"; did you mean {suggestion!r}?" if suggestion else ""
        super().__init__(f"Native slot {slot!r} accepts no parameter {key!r}{hint}")
        self.slot = slot
        self.key = key
        self.suggestion = suggestion


class NativeConfigConflictError(NativeConfigError):
    def __init__(self, slot: str, key: str, config_field: str) -> None:
        super().__init__(
            f"Native key {key!r} in slot {slot!r} conflicts with explicitly set config field {config_field!r}; "
            f"set it in exactly one place"
        )
        self.slot = slot
        self.key = key
        self.config_field = config_field


class CallError(ClientwrightError):
    """Base for errors raised while executing a call; adapters dual-inherit these."""


class CircuitOpenError(CallError):
    """Local refusal: the circuit for this key is open."""

    def __init__(self, key: str, retry_after: float | None = None) -> None:
        suffix = f" (retry in ~{retry_after:.1f}s)" if retry_after is not None else ""
        super().__init__(f"Circuit open for {key!r}{suffix}")
        self.key = key
        self.retry_after = retry_after


class DeadlineExceededError(CallError):
    """The total deadline of the logical call was exhausted."""

    def __init__(self, total: float) -> None:
        super().__init__(f"Deadline of {total:.3f}s exhausted")
        self.total = total


class TooManyRedirectsError(CallError):
    def __init__(self, hops: int) -> None:
        super().__init__(f"Exceeded {hops} redirect hops")
        self.hops = hops


class NotReplayableError(CallError):
    """The request body cannot be replayed, so the required repeat is impossible."""


__all__ = [
    "CallError",
    "CircuitOpenError",
    "ClientwrightError",
    "DeadlineExceededError",
    "NativeConfigConflictError",
    "NativeConfigError",
    "NotReplayableError",
    "ReservedNativeKeyError",
    "TooManyRedirectsError",
    "UnknownAdapterError",
    "UnknownNativeKeyError",
    "UnknownNativeSlotError",
    "UnsupportedCapabilityError",
]
