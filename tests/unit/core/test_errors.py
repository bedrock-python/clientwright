"""Kernel error hierarchy and message contracts."""

from __future__ import annotations

from clientwright.core.errors import (
    CallError,
    CircuitOpenError,
    ClientwrightError,
    DeadlineExceededError,
    NativeConfigConflictError,
    NativeConfigError,
    NotReplayableError,
    ReservedNativeKeyError,
    TooManyRedirectsError,
    UnknownAdapterError,
    UnknownNativeKeyError,
    UnknownNativeSlotError,
    UnsupportedCapabilityError,
)

# --- hierarchy ---


def test__every_call_error__is_a_clientwright_error() -> None:
    for error_type in (CircuitOpenError, DeadlineExceededError, TooManyRedirectsError, NotReplayableError):
        assert issubclass(error_type, CallError)
        assert issubclass(error_type, ClientwrightError)


def test__build_time_errors__are_not_call_errors() -> None:
    for error_type in (UnknownAdapterError, UnsupportedCapabilityError, NativeConfigError):
        assert issubclass(error_type, ClientwrightError)
        assert not issubclass(error_type, CallError)


def test__native_config_errors__share_one_base() -> None:
    for error_type in (UnknownNativeSlotError, ReservedNativeKeyError, UnknownNativeKeyError):
        assert issubclass(error_type, NativeConfigError)


# --- messages ---


def test__unknown_adapter__lists_known_or_none() -> None:
    assert "httpx, urllib3" in str(UnknownAdapterError("nope", ("httpx", "urllib3")))
    assert "<none>" in str(UnknownAdapterError("nope", ()))


def test__circuit_open__retry_after_suffix_is_optional() -> None:
    with_hint = CircuitOpenError("https://a:443", retry_after=12.34)
    assert "retry in ~12.3s" in str(with_hint)
    assert with_hint.retry_after == 12.34
    without_hint = CircuitOpenError("https://a:443")
    assert "retry in" not in str(without_hint)


def test__deadline__formats_the_total() -> None:
    assert "0.050s" in str(DeadlineExceededError(0.05))


def test__too_many_redirects__names_the_hop_limit() -> None:
    error = TooManyRedirectsError(5)
    assert "5" in str(error)
    assert error.hops == 5


def test__unknown_native_key__suggestion_is_optional() -> None:
    with_hint = UnknownNativeKeyError("client", "timeot", suggestion="timeout")
    assert "did you mean 'timeout'" in str(with_hint)
    without_hint = UnknownNativeKeyError("client", "zzz")
    assert "did you mean" not in str(without_hint)


def test__reserved_key_and_conflict__both_name_the_slot_and_key() -> None:
    reserved = ReservedNativeKeyError("client", "timeout", "owned by TimeoutConfig")
    assert "'timeout'" in str(reserved)
    assert "owned by TimeoutConfig" in str(reserved)
    conflict = NativeConfigConflictError("client", "verify", "tls.verify")
    assert "exactly one place" in str(conflict)
    assert conflict.config_field == "tls.verify"


def test__unknown_slot__lists_adapter_slots() -> None:
    error = UnknownNativeSlotError("nope", ("client", "transport"))
    assert "client, transport" in str(error)
