"""String values for enum fields must become real members.

Config routinely arrives from YAML, env vars or a settings model, where these
fields are plain strings. The engine compares members with ``is``, so a bare
string would match no branch and silently take the fallback - most dangerously
``RetryConfig(mode="delegated")``, which used to disable retries entirely
instead of delegating them.
"""

from __future__ import annotations

import pytest

from clientwright.core.capabilities import Capability, ConfigApplicationReport, Support
from clientwright.core.config import (
    CallerOverride,
    CircuitBreakerConfig,
    ClientConfig,
    RedirectMode,
    RetryConfig,
    RetryMode,
    UnsupportedPolicy,
)
from clientwright.core.errors import UnsupportedCapabilityError
from clientwright.core.model import CircuitKey, FailureKind, ResolvedTimeouts
from clientwright.core.plan import compile_plan
from tests.helpers.engine import FAKE_CAPABILITIES


def test__client_config_strings__become_enum_members() -> None:
    config = ClientConfig(
        service_name="svc",
        redirects="native",
        caller_override="config_wins",
        on_unsupported="strict",
    )
    assert config.redirects is RedirectMode.NATIVE
    assert config.caller_override is CallerOverride.CONFIG_WINS
    assert config.on_unsupported is UnsupportedPolicy.STRICT


def test__retry_mode_string__actually_delegates_instead_of_disabling_retries() -> None:
    config = ClientConfig(service_name="svc", retry=RetryConfig(mode="delegated"))
    assert config.retry is not None
    assert config.retry.mode is RetryMode.DELEGATED
    plan = compile_plan(config, FAKE_CAPABILITIES, native_timeout_defaults=ResolvedTimeouts())
    assert plan.retry_policy is None  # the loop lives below the seam...
    assert not plan.emit_attempt_metrics  # ...and the plan knows it, so attempts stay honest


def test__circuit_key_string__reaches_the_key_computation() -> None:
    config = ClientConfig(service_name="svc", circuit_breaker=CircuitBreakerConfig(key="origin_route"))
    assert config.circuit_breaker is not None
    assert config.circuit_breaker.key is CircuitKey.ORIGIN_ROUTE


def test__strict_policy_as_a_string__still_fails_the_build() -> None:
    report = ConfigApplicationReport(adapter="fake", dropped={Capability.HTTP2: "no h2"})
    config = ClientConfig(service_name="svc", on_unsupported="strict")
    with pytest.raises(UnsupportedCapabilityError, match="cannot express"):
        report.enforce(config.on_unsupported)


def test__enum_members__pass_through_untouched() -> None:
    config = ClientConfig(service_name="svc", redirects=RedirectMode.NATIVE)
    assert config.redirects is RedirectMode.NATIVE


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"redirects": "sideways"}, "redirects must be one of"),
        ({"caller_override": "loudest"}, "caller_override must be one of"),
        ({"on_unsupported": "strikt"}, "on_unsupported must be one of"),
    ],
)
def test__typo_in_an_enum_field__fails_loudly(kwargs: dict[str, str], expected: str) -> None:
    with pytest.raises(ValueError, match=expected):
        ClientConfig(service_name="svc", **kwargs)  # type: ignore[arg-type]


def test__typo_in_nested_configs__fails_loudly() -> None:
    with pytest.raises(ValueError, match="mode must be one of"):
        RetryConfig(mode="delegatd")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="key must be one of"):
        CircuitBreakerConfig(key="orgin")  # type: ignore[arg-type]


def test__support_levels__still_compare_by_identity() -> None:
    # A sanity anchor for the enum family the coercion does NOT touch: these are
    # produced by adapters, never parsed from user config.
    assert FAKE_CAPABILITIES.support_of(next(iter(FAKE_CAPABILITIES.support))) is Support.EMULATED
    assert FailureKind.STATUS is FailureKind("status")
