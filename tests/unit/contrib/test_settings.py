"""contrib units: the settings models and their translation into ClientConfig."""

from __future__ import annotations

import dataclasses
import logging

import pytest

pytest.importorskip("pydantic", reason="requires the [settings] extra")

from pydantic import ValidationError

from clientwright import (
    UNSET,
    CircuitBreakerConfig,
    CircuitKey,
    ClientConfig,
    FailureKind,
    NativeOptions,
    ObservabilityConfig,
    PoolConfig,
    ProxyConfig,
    RetryConfig,
    RetryMode,
    TimeoutConfig,
    TlsConfig,
    UnsupportedPolicy,
    build_sync,
    client_config_from_settings,
)
from clientwright.contrib import settings as settings_module
from clientwright.contrib.settings import (
    BaseCircuitBreakerSettings,
    BaseClientSettings,
    BaseObservabilitySettings,
    BasePoolSettings,
    BaseProxySettings,
    BaseRetrySettings,
    BaseTimeoutSettings,
    BaseTlsSettings,
)

# --- the models are the dataclasses, written once ---

PAIRS = [
    (BaseTimeoutSettings, TimeoutConfig, set()),
    (BasePoolSettings, PoolConfig, set()),
    (BaseRetrySettings, RetryConfig, set()),
    (BaseCircuitBreakerSettings, CircuitBreakerConfig, set()),
    (BaseTlsSettings, TlsConfig, set()),
    (BaseProxySettings, ProxyConfig, set()),
    (BaseObservabilitySettings, ObservabilityConfig, {"url_masker"}),
    (BaseClientSettings, ClientConfig, {"service_name"}),
]


@pytest.mark.parametrize(("model", "dataclass", "not_env_shaped"), PAIRS, ids=[m.__name__ for m, _, _ in PAIRS])
def test__every_model__names_exactly_the_dataclass_fields(
    model: type, dataclass: type, not_env_shaped: set[str]
) -> None:
    assert set(model.model_fields) == {f.name for f in dataclasses.fields(dataclass)} - not_env_shaped


def test__defaults__are_the_dataclass_defaults() -> None:
    assert BaseClientSettings().to_config("orders") == ClientConfig(service_name="orders")


def test__no_model__is_a_base_settings() -> None:
    pydantic_settings = pytest.importorskip("pydantic_settings", reason="requires the [settings] extra")
    for name in settings_module.__all__:
        assert not issubclass(getattr(settings_module, name), pydantic_settings.BaseSettings), name


# --- the environment ---


def test__nested_in_a_base_settings__reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    pydantic_settings = pytest.importorskip("pydantic_settings", reason="requires the [settings] extra")

    class Settings(pydantic_settings.BaseSettings):
        model_config = pydantic_settings.SettingsConfigDict(env_nested_delimiter="__")

        warehouse: BaseClientSettings = BaseClientSettings()

    monkeypatch.setenv("WAREHOUSE__BASE_URL", "https://wh.example.com")
    monkeypatch.setenv("WAREHOUSE__TIMEOUT__TOTAL", "10")
    monkeypatch.setenv("WAREHOUSE__TIMEOUT__CONNECT", "2")
    monkeypatch.setenv("WAREHOUSE__POOL__HTTP2", "true")
    monkeypatch.setenv("WAREHOUSE__RETRY__MAX_ATTEMPTS", "5")
    monkeypatch.setenv("WAREHOUSE__RETRY__RETRYABLE_STATUS", "[429, 500]")
    monkeypatch.setenv("WAREHOUSE__CIRCUIT_BREAKER__FAIL_THRESHOLD", "2")
    monkeypatch.setenv("WAREHOUSE__TLS__CERT", '["client.pem", "client.key"]')
    monkeypatch.setenv("WAREHOUSE__PROXY__URL", "http://proxy:3128")
    monkeypatch.setenv("WAREHOUSE__ON_UNSUPPORTED", "strict")

    config = Settings().warehouse.to_config("warehouse")

    assert config == ClientConfig(
        service_name="warehouse",
        base_url="https://wh.example.com",
        timeout=TimeoutConfig(total=10.0, connect=2.0),
        pool=PoolConfig(http2=True),
        retry=RetryConfig(max_attempts=5, retryable_status=frozenset({429, 500})),
        circuit_breaker=CircuitBreakerConfig(fail_threshold=2),
        tls=TlsConfig(cert=("client.pem", "client.key")),
        proxy=ProxyConfig(url="http://proxy:3128"),
        on_unsupported=UnsupportedPolicy.STRICT,
    )


def test__bare_variables__cannot_reach_a_section(monkeypatch: pytest.MonkeyPatch) -> None:
    pydantic_settings = pytest.importorskip("pydantic_settings", reason="requires the [settings] extra")

    class Settings(pydantic_settings.BaseSettings):
        model_config = pydantic_settings.SettingsConfigDict(env_nested_delimiter="__")

        warehouse: BaseClientSettings = BaseClientSettings()

    class LeakySection(pydantic_settings.BaseSettings):
        base_url: str | None = None

    monkeypatch.setenv("BASE_URL", "https://leak.example.com")
    monkeypatch.setenv("TIMEOUT", "1")
    monkeypatch.setenv("TOTAL", "1")
    monkeypatch.setenv("MAX_ATTEMPTS", "9")
    monkeypatch.setenv("HTTP2", "true")
    monkeypatch.setenv("VERIFY", "false")

    assert LeakySection().base_url == "https://leak.example.com"  # what a BaseSettings section would do
    assert Settings().warehouse.to_config("warehouse") == ClientConfig(service_name="warehouse")


def test__null_in_the_environment__disables_a_section_and_unbounds_a_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    pydantic_settings = pytest.importorskip("pydantic_settings", reason="requires the [settings] extra")

    class Settings(pydantic_settings.BaseSettings):
        model_config = pydantic_settings.SettingsConfigDict(env_nested_delimiter="__", env_parse_none_str="null")

        warehouse: BaseClientSettings = BaseClientSettings()

    monkeypatch.setenv("WAREHOUSE__RETRY", "null")
    monkeypatch.setenv("WAREHOUSE__TIMEOUT__READ", "null")

    config = Settings().warehouse.to_config("warehouse")

    assert config.retry is None
    assert config.timeout.read is None
    assert config.timeout.write is UNSET


# --- UNSET, None and the env spellings ---


def test__an_unset_knob__stays_unset_and_null_is_unbounded() -> None:
    assert BaseTimeoutSettings().to_config().read is UNSET
    assert BaseTimeoutSettings(read=None).to_config().read is None
    assert BaseTimeoutSettings(read=2.0).to_config().read == 2.0
    assert BasePoolSettings().to_config().max_connections_per_host is UNSET
    assert BasePoolSettings().to_config().http2 is UNSET
    assert BasePoolSettings(http2=False).to_config().http2 is False


def test__enums_sets_and_levels__are_coerced_from_their_env_spellings() -> None:
    retry = BaseRetrySettings(mode="delegated", retryable_kinds=["dns_error"], methods=["GET"]).to_config()
    assert retry.mode is RetryMode.DELEGATED
    assert retry.retryable_kinds == frozenset({FailureKind.DNS_ERROR})
    assert retry.methods == frozenset({"GET"})
    assert BaseCircuitBreakerSettings(key="origin_route").to_config().key is CircuitKey.ORIGIN_ROUTE
    assert BaseObservabilitySettings(success_log_level="debug").to_config().success_log_level == logging.DEBUG
    assert BaseObservabilitySettings(success_log_level=30).to_config().success_log_level == logging.WARNING
    with pytest.raises(ValidationError, match="unknown log level"):
        BaseObservabilitySettings(success_log_level="LOUD")


def test__sections__disable_with_none_and_proxy_appears_on_demand() -> None:
    class Batch(BaseClientSettings):
        retry: None = None
        circuit_breaker: None = None

    config = Batch().to_config("batch")
    assert config.retry is None
    assert config.circuit_breaker is None
    assert config.proxy is None
    assert BaseClientSettings(proxy=BaseProxySettings(from_env=True)).to_config("x").proxy == ProxyConfig(from_env=True)


def test__headers_and_native__reach_the_config() -> None:
    config = BaseClientSettings(headers={"User-Agent": "svc/1"}, native={"client": {"trust_env": False}}).to_config(
        "svc"
    )
    assert config.headers == {"User-Agent": "svc/1"}
    assert config.native == NativeOptions.of(client={"trust_env": False})


def test__bad_values__fail_at_load_with_the_field_path() -> None:
    with pytest.raises(ValidationError, match=r"timeout\.total"):
        BaseClientSettings(timeout={"total": 0})
    with pytest.raises(ValidationError, match="base_url"):
        BaseClientSettings(base_url="ftp://nope")
    with pytest.raises(ValidationError, match="max_attempts"):
        BaseRetrySettings(max_attempts=0)
    with pytest.raises(ValidationError, match="mutually exclusive"):
        BaseProxySettings(url="http://proxy:3128", from_env=True)


# --- the legacy converter ---


def test__the_legacy_converter__passes_a_base_client_settings_through_to_to_config() -> None:
    settings = BaseClientSettings(
        base_url="https://auth.example.com",
        pool={"max_connections": 7},
        retry={"multiplier": 3.0},
        tls={"verify": False},
        proxy={"url": "http://proxy:3128"},
    )

    config = client_config_from_settings(settings, "auth-orchestrator")

    assert config == settings.to_config("auth-orchestrator")
    assert config.pool.max_connections == 7
    assert config.retry is not None and config.retry.multiplier == 3.0
    assert config.tls == TlsConfig(verify=False)
    assert config.proxy == ProxyConfig(url="http://proxy:3128")


def test__a_config_from_settings__builds_the_native_client() -> None:
    httpx = pytest.importorskip("httpx", reason="requires the [httpx] extra")
    config = BaseClientSettings(base_url="https://api.example.com", pool={"http2": False}).to_config("api")
    client = build_sync("httpx", config)
    try:
        assert type(client) is httpx.Client
    finally:
        client.close()
