"""Runtime wiring, plan compilation, report enforcement and client handles."""

from __future__ import annotations

import logging

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
from clientwright.core.config import ClientConfig, PoolConfig, RetryConfig, RetryMode, UnsupportedPolicy
from clientwright.core.errors import UnsupportedCapabilityError
from clientwright.core.model import FailureKind
from clientwright.core.plan import ClientHandle, ClientRuntime, compile_plan, inspect_client, register_handle
from clientwright.core.testing import ManualClock
from tests.helpers.engine import FAKE_CAPABILITIES, NATIVE_DEFAULTS, make_config

# --- ClientRuntime ---


def test__defaults__circuits_and_budgets_but_no_limiters() -> None:
    runtime = ClientRuntime.for_config(make_config(circuit_breaker=None))
    runtime_full = ClientRuntime.for_config(ClientConfig(service_name="svc"))
    assert runtime.circuits is None
    assert runtime_full.circuits is not None
    assert runtime_full.retry_budgets is not None  # default budget_ratio=0.1
    assert runtime_full.async_limiter is None  # per-host limit is UNSET by default
    assert runtime_full.sync_limiter is None


def test__per_host_limit__creates_both_limiters() -> None:
    config = make_config(pool=PoolConfig(max_connections_per_host=3))
    runtime = ClientRuntime.for_config(config)
    assert runtime.async_limiter is not None
    assert runtime.sync_limiter is not None


def test__no_retry__no_budgets() -> None:
    runtime = ClientRuntime.for_config(make_config(retry=None))
    assert runtime.retry_budgets is None


def test__injected_clock__used_verbatim() -> None:
    clock = ManualClock(start=42.0)
    runtime = ClientRuntime.for_config(make_config(), clock=clock)
    assert runtime.clock() == 42.0


# --- compile_plan ---


def test__owned_retry__policy_compiled_and_attempt_metrics_on() -> None:
    plan = compile_plan(make_config(), FAKE_CAPABILITIES, native_timeout_defaults=NATIVE_DEFAULTS)
    assert plan.retry_policy is not None
    assert plan.emit_attempt_metrics


def test__delegated_retry__no_policy_and_attempt_metrics_honestly_off() -> None:
    config = make_config(retry=RetryConfig(mode=RetryMode.DELEGATED))
    plan = compile_plan(config, FAKE_CAPABILITIES, native_timeout_defaults=NATIVE_DEFAULTS)
    assert plan.retry_policy is None  # attempts live below the seam
    assert not plan.emit_attempt_metrics


def test__no_retry__no_policy_but_metrics_stay_on() -> None:
    plan = compile_plan(make_config(retry=None), FAKE_CAPABILITIES, native_timeout_defaults=NATIVE_DEFAULTS)
    assert plan.retry_policy is None
    assert plan.emit_attempt_metrics


def test__origin_limiter__only_when_per_host_set_and_emulated() -> None:
    config = make_config(pool=PoolConfig(max_connections_per_host=2))
    emulated = compile_plan(config, FAKE_CAPABILITIES, native_timeout_defaults=NATIVE_DEFAULTS)
    assert emulated.use_origin_limiter
    native_caps = AdapterCapabilities(
        adapter="native-caps",
        seam="test",
        granularity=SeamGranularity.LOGICAL,
        boundary=DurationBoundary.HEADERS,
        support={Capability.POOL_LIMIT_PER_HOST: Support.NATIVE},
        emits=frozenset(FailureKind),
    )
    native = compile_plan(config, native_caps, native_timeout_defaults=NATIVE_DEFAULTS)
    assert not native.use_origin_limiter  # the pool itself enforces it
    unset = compile_plan(make_config(), FAKE_CAPABILITIES, native_timeout_defaults=NATIVE_DEFAULTS)
    assert not unset.use_origin_limiter


def test__dead_retryable_kinds__reported_for_unreachable_kinds() -> None:
    narrow = AdapterCapabilities(
        adapter="narrow",
        seam="test",
        granularity=SeamGranularity.LOGICAL,
        boundary=DurationBoundary.HEADERS,
        support={},
        emits=frozenset({FailureKind.CONNECT_ERROR}),
    )
    plan = compile_plan(make_config(), narrow, native_timeout_defaults=NATIVE_DEFAULTS)
    assert FailureKind.READ_TIMEOUT in plan.report.dead_retryable_kinds
    assert FailureKind.CONNECT_ERROR not in plan.report.dead_retryable_kinds


# --- dead retryable kinds ---


def test__collapsed_kind__reachable_through_its_target() -> None:
    capabilities = AdapterCapabilities(
        adapter="c",
        seam="test",
        granularity=SeamGranularity.LOGICAL,
        boundary=DurationBoundary.HEADERS,
        support={},
        emits=frozenset({FailureKind.CONNECT_ERROR}),
        collapses={FailureKind.DNS_ERROR: FailureKind.CONNECT_ERROR},
    )
    dead = dead_retryable_kinds(frozenset({FailureKind.DNS_ERROR, FailureKind.READ_TIMEOUT}), capabilities)
    assert dead == frozenset({FailureKind.READ_TIMEOUT})


def test__support_of_missing_capability__absent() -> None:
    assert FAKE_CAPABILITIES.support_of(Capability.HTTP3) is Support.ABSENT


# --- report enforcement ---


def _report(**overrides: object) -> ConfigApplicationReport:
    defaults: dict[str, object] = {"adapter": "fake", "dropped": {Capability.HTTP2: "no h2 here"}}
    defaults.update(overrides)
    return ConfigApplicationReport(**defaults)  # type: ignore[arg-type]


def test__strict__raises_with_every_problem_listed() -> None:
    report = _report(dead_retryable_kinds=frozenset({FailureKind.DNS_ERROR}))
    with pytest.raises(UnsupportedCapabilityError, match="no h2 here") as excinfo:
        report.enforce(UnsupportedPolicy.STRICT)
    assert "dns_error" in str(excinfo.value)


def test__warn__logs_instead_of_raising(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="clientwright.capabilities"):
        _report().enforce(UnsupportedPolicy.WARN)
    assert any("no h2 here" in message for message in caplog.messages)


def test__ignore__stays_silent(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="clientwright.capabilities"):
        _report().enforce(UnsupportedPolicy.IGNORE)
    assert not caplog.messages


def test__clean_report__no_issues_even_under_strict() -> None:
    ConfigApplicationReport(adapter="fake").enforce(UnsupportedPolicy.STRICT)


# --- client handles ---


def _handle() -> object:
    plan = compile_plan(make_config(), FAKE_CAPABILITIES, native_timeout_defaults=NATIVE_DEFAULTS)
    return ClientHandle(
        client=object(),
        adapter="fake",
        capabilities=FAKE_CAPABILITIES,
        report=plan.report,
        runtime=ClientRuntime.for_config(make_config()),
        plan=plan,
    )


def test__ordinary_client__handle_lives_on_the_instance() -> None:
    class Client:
        pass

    client = Client()
    handle = _handle()
    register_handle(client, handle)  # type: ignore[arg-type]
    assert inspect_client(client) is handle


def test__slots_only_client__falls_back_to_the_weak_registry() -> None:
    class SlotsClient:
        __slots__ = ("__weakref__",)

    client = SlotsClient()
    handle = _handle()
    register_handle(client, handle)  # type: ignore[arg-type]
    assert inspect_client(client) is handle


def test__foreign_object__inspect_returns_none() -> None:
    assert inspect_client(object()) is None
