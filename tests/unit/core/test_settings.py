"""Structural settings protocols mapped into ClientConfig."""

from __future__ import annotations

import clientwright


def test__structural_settings__mapped_into_config() -> None:
    class Retry:
        max_attempts = 5
        initial_backoff = 0.2
        max_backoff = 4.0
        backoff_multiplier = 3.0

    class Settings:
        base_url = "https://api.example.com"
        timeout_seconds = 12.0
        connect_timeout_seconds = 3.0
        max_connections = 50
        max_keepalive_connections = 10
        enable_http2 = True
        verify = False
        logging_enabled = True
        metrics_enabled = True
        tracing_enabled = False
        retry = Retry()
        circuit_breaker = None

    config = clientwright.client_config_from_settings(Settings(), "svc")
    assert config.base_url == "https://api.example.com"
    assert config.timeout.total == 12.0
    assert config.retry is not None and config.retry.max_attempts == 5
    assert config.circuit_breaker is None
    assert config.observability.tracing is False
