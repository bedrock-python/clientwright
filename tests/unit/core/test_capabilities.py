"""Native passthrough validation and capability reporting."""

from __future__ import annotations

import pytest

from clientwright.core.capabilities import (
    AdapterCapabilities,
    Capability,
    ConfigApplicationReport,
    DurationBoundary,
    SeamGranularity,
    Support,
    dead_retryable_kinds,
)
from clientwright.core.config import NativeOptions, UnsupportedPolicy
from clientwright.core.errors import (
    NativeConfigConflictError,
    ReservedNativeKeyError,
    UnknownNativeKeyError,
    UnknownNativeSlotError,
    UnsupportedCapabilityError,
)
from clientwright.core.model import FailureKind
from clientwright.core.native import validate_native


def _target(*, timeout: float = 1.0, limits: object = None) -> None:
    return None


def _kwargs_target(**kwargs: object) -> None:
    return None


def validate(native: NativeOptions, **overrides: object) -> dict[str, dict[str, object]]:
    defaults: dict[str, object] = {
        "slots": frozenset({"client", "transport"}),
        "reserved": {"client": {"transport": "owned by clientwright"}},
        "allowed": {"client": None, "transport": frozenset({"uds"})},
        "signature_targets": {"client": _target},
        "config_conflicts": {},
    }
    defaults.update(overrides)
    return validate_native(native, **defaults)  # type: ignore[arg-type]


# --- validate_native ---


def test__valid_options__returned_per_slot() -> None:
    result = validate(NativeOptions.of(client={"timeout": 5.0}, transport={"uds": "./sock"}))
    assert result == {"client": {"timeout": 5.0}, "transport": {"uds": "./sock"}}


def test__unknown_slot__lists_known_slots() -> None:
    with pytest.raises(UnknownNativeSlotError, match="client, transport"):
        validate(NativeOptions.of(connector={"x": 1}))


def test__reserved_key__explains_alternative() -> None:
    with pytest.raises(ReservedNativeKeyError, match="owned by clientwright"):
        validate(NativeOptions.of(client={"transport": object()}))


def test__typo_against_signature__suggests_correction() -> None:
    with pytest.raises(UnknownNativeKeyError, match="did you mean 'timeout'"):
        validate(NativeOptions.of(client={"timeuot": 5.0}))


def test__allowlist_slot__rejects_unknown_key() -> None:
    with pytest.raises(UnknownNativeKeyError):
        validate(NativeOptions.of(transport={"nope": 1}))


def test__var_keyword_signature__accepts_anything() -> None:
    result = validate(
        NativeOptions.of(client={"whatever": 1}),
        signature_targets={"client": _kwargs_target},
    )
    assert result["client"] == {"whatever": 1}


def test__conflict_with_explicit_config__raises() -> None:
    with pytest.raises(NativeConfigConflictError, match=r"pool\.max_connections"):
        validate(
            NativeOptions.of(client={"limits": object()}),
            config_conflicts={"client": {"limits": "pool.max_connections"}},
        )


CAPS = AdapterCapabilities(
    adapter="fake",
    seam="test",
    granularity=SeamGranularity.LOGICAL,
    boundary=DurationBoundary.HEADERS,
    support={Capability.TIMEOUT_TOTAL: Support.EMULATED},
    emits=frozenset({FailureKind.CONNECT_TIMEOUT, FailureKind.STATUS}),
    collapses={FailureKind.DNS_ERROR: FailureKind.CONNECT_ERROR, FailureKind.POOL_TIMEOUT: FailureKind.CONNECT_TIMEOUT},
)


# --- dead retryable kinds ---


def test__unreachable_kind__reported_dead() -> None:
    dead = dead_retryable_kinds(frozenset({FailureKind.READ_TIMEOUT, FailureKind.CONNECT_TIMEOUT}), CAPS)
    assert dead == frozenset({FailureKind.READ_TIMEOUT})


def test__collapsed_kind__reachable_through_target() -> None:
    dead = dead_retryable_kinds(frozenset({FailureKind.POOL_TIMEOUT}), CAPS)
    assert dead == frozenset()


def test__collapse_into_unemitted_target__still_dead() -> None:
    dead = dead_retryable_kinds(frozenset({FailureKind.DNS_ERROR}), CAPS)
    assert dead == frozenset({FailureKind.DNS_ERROR})


# --- report enforcement ---


def _report() -> ConfigApplicationReport:
    return ConfigApplicationReport(
        adapter="fake",
        dropped={Capability.TIMEOUT_WRITE: "no write timeout"},
        dead_retryable_kinds=frozenset({FailureKind.READ_TIMEOUT}),
    )


def test__strict__raises_with_every_issue_listed() -> None:
    with pytest.raises(UnsupportedCapabilityError, match="timeout_write") as excinfo:
        _report().enforce(UnsupportedPolicy.STRICT)
    assert "read_timeout" in str(excinfo.value)


def test__warn_and_ignore__do_not_raise() -> None:
    _report().enforce(UnsupportedPolicy.WARN)
    _report().enforce(UnsupportedPolicy.IGNORE)


def test__clean_report__passes_strict() -> None:
    ConfigApplicationReport(adapter="fake").enforce(UnsupportedPolicy.STRICT)
