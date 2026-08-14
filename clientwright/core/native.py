"""Validation of raw native passthrough options.

``PoolManager(**kw)``-style constructors swallow any typo silently; here every
unknown slot, reserved key, misspelled parameter and config collision is a
loud, actionable error at build time.
"""

from __future__ import annotations

import difflib
import inspect
from collections.abc import Callable, Mapping

from .config import NativeOptions
from .errors import (
    NativeConfigConflictError,
    ReservedNativeKeyError,
    UnknownNativeKeyError,
    UnknownNativeSlotError,
)


def _suggest(key: str, candidates: list[str]) -> str | None:
    matches = difflib.get_close_matches(key, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _signature_keys(target: Callable[..., object]) -> tuple[frozenset[str], bool]:
    """Keyword-acceptable parameter names and whether **kwargs is present."""
    signature = inspect.signature(target)
    names = set()
    has_var_keyword = False
    for parameter in signature.parameters.values():
        if parameter.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
            names.add(parameter.name)
        elif parameter.kind is inspect.Parameter.VAR_KEYWORD:
            has_var_keyword = True
    names.discard("self")
    return frozenset(names), has_var_keyword


def validate_native(
    native: NativeOptions,
    *,
    slots: frozenset[str],
    reserved: Mapping[str, Mapping[str, str]],
    allowed: Mapping[str, frozenset[str] | None],
    signature_targets: Mapping[str, Callable[..., object]],
    config_conflicts: Mapping[str, Mapping[str, str]],
) -> dict[str, dict[str, object]]:
    """Validate and return per-slot native kwargs.

    ``config_conflicts`` maps slot -> {native_key: explicitly-set config field};
    the adapter builds it from fields the user actually set (not UNSET), so the
    "conflict is an error" rule fires exactly when both sides were specified.
    """
    validated: dict[str, dict[str, object]] = {}
    for slot, values in native.slots.items():
        if slot not in slots:
            raise UnknownNativeSlotError(slot, tuple(sorted(slots)))
        reserved_keys = reserved.get(slot, {})
        allowlist = allowed.get(slot)
        signature_keys: frozenset[str] | None = None
        has_var_keyword = False
        if allowlist is None and slot in signature_targets:
            signature_keys, has_var_keyword = _signature_keys(signature_targets[slot])
        conflicts = config_conflicts.get(slot, {})
        slot_values: dict[str, object] = {}
        for key, value in values.items():
            if key in reserved_keys:
                raise ReservedNativeKeyError(slot, key, reserved_keys[key])
            if key in conflicts:
                raise NativeConfigConflictError(slot, key, conflicts[key])
            if allowlist is not None:
                if key not in allowlist:
                    raise UnknownNativeKeyError(slot, key, _suggest(key, sorted(allowlist)))
            elif signature_keys is not None and not has_var_keyword and key not in signature_keys:
                raise UnknownNativeKeyError(slot, key, _suggest(key, sorted(signature_keys)))
            slot_values[key] = value
        validated[slot] = slot_values
    return validated


__all__ = ["validate_native"]
