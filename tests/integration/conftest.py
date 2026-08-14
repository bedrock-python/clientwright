"""Integration fixtures: fault-injecting origin plus client builders."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from clientwright import AdapterDeps, ClientConfig
from clientwright.core.testing import OriginServer, RecordingMetrics


@pytest.fixture
def origin() -> Iterator[OriginServer]:
    with OriginServer() as server:
        yield server


@pytest.fixture
def metrics() -> RecordingMetrics:
    return RecordingMetrics()


@pytest.fixture
def deps(metrics: RecordingMetrics) -> AdapterDeps:
    return AdapterDeps(metrics=metrics)


def base_config(origin: OriginServer, **overrides: object) -> ClientConfig:
    return ClientConfig(service_name="conformance", base_url=origin.url, **overrides)  # type: ignore[arg-type]
