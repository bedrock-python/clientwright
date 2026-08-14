"""Config validation, the UNSET sentinel and NativeOptions."""

from __future__ import annotations

import pytest

from clientwright.core.config import (
    UNSET,
    CircuitBreakerConfig,
    ClientConfig,
    NativeOptions,
    PoolConfig,
    ProxyConfig,
    RetryConfig,
    TimeoutConfig,
    is_set,
    resolve,
)

# --- UNSET ---


def test__unset__falsy_singleton_with_repr() -> None:
    assert not UNSET
    assert repr(UNSET) == "UNSET"
    assert not is_set(UNSET)
    assert is_set(None)


def test__resolve__returns_value_or_fallback() -> None:
    assert resolve(UNSET, 5) == 5
    assert resolve(7, 5) == 7
    assert resolve(None, 5) is None


# --- validation ---


def test__timeout_config__rejects_non_positive() -> None:
    with pytest.raises(ValueError, match=r"timeout\.total"):
        TimeoutConfig(total=0)


def test__pool_config__rejects_non_positive() -> None:
    with pytest.raises(ValueError, match=r"pool\.max_connections"):
        PoolConfig(max_connections=0)


def test__retry_config__rejects_bad_jitter_and_attempts() -> None:
    with pytest.raises(ValueError, match="jitter"):
        RetryConfig(jitter=1.5)
    with pytest.raises(ValueError, match="max_attempts"):
        RetryConfig(max_attempts=0)


def test__retry_config__rejects_shrinking_multiplier_and_bad_budget() -> None:
    with pytest.raises(ValueError, match="multiplier"):
        RetryConfig(multiplier=0.5)
    with pytest.raises(ValueError, match="budget_ratio"):
        RetryConfig(budget_ratio=1.5)
    with pytest.raises(ValueError, match="budget_ratio"):
        RetryConfig(budget_ratio=0.0)


def test__circuit_breaker_config__rejects_non_positive_knobs() -> None:
    with pytest.raises(ValueError, match="fail_threshold"):
        CircuitBreakerConfig(fail_threshold=0)
    with pytest.raises(ValueError, match="half_open_max_calls"):
        CircuitBreakerConfig(half_open_max_calls=0)
    with pytest.raises(ValueError, match="max_keys"):
        CircuitBreakerConfig(max_keys=0)


def test__proxy_config__url_and_from_env_are_exclusive() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        ProxyConfig(url="http://proxy:3128", from_env=True)


def test__client_config__rejects_empty_service_and_bad_base_url() -> None:
    with pytest.raises(ValueError, match="service_name"):
        ClientConfig(service_name="  ")
    with pytest.raises(ValueError, match="base_url"):
        ClientConfig(service_name="x", base_url="ftp://nope")


def test__client_config__rejects_negative_max_redirects() -> None:
    with pytest.raises(ValueError, match="max_redirects"):
        ClientConfig(service_name="svc", max_redirects=-1)


def test__client_config__defaults_are_sane() -> None:
    config = ClientConfig(service_name="svc")
    assert config.retry is not None and config.retry.max_attempts == 3
    assert config.circuit_breaker is not None
    assert config.redirects.value == "owned"


# --- NativeOptions ---


def test__of_and_for_slot__copy_in_and_out() -> None:
    source = {"limits": 5}
    options = NativeOptions.of(client=source)
    source["limits"] = 99  # the builder took a copy, later mutation is invisible
    assert options.for_slot("client") == {"limits": 5}
    assert options.for_slot("missing") == {}
    options.for_slot("client")["limits"] = 0  # for_slot hands out a copy too
    assert options.for_slot("client") == {"limits": 5}
