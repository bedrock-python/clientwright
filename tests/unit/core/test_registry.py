"""Adapter registry: lazy resolution and the zero-import capabilities matrix."""

from __future__ import annotations

import pytest

import clientwright
from clientwright.core.errors import UnknownAdapterError
from clientwright.core.registry import _ADAPTERS, _CAPABILITIES, register_adapter, resolve_adapter
from clientwright.core.telemetry.null import NullMetrics


def test__unknown_adapter__error_lists_known() -> None:
    with pytest.raises(UnknownAdapterError, match="httpx"):
        resolve_adapter("nope")


def test__register_adapter__validates_target_shape() -> None:
    with pytest.raises(ValueError, match=r"module\.path:Attribute"):
        register_adapter("bad", "no-colon", "also-bad")


def test__register_adapter__third_party_target_resolves_lazily() -> None:
    register_adapter(
        "fake-adapter",
        "clientwright.core.telemetry.null:NullMetrics",
        "clientwright.core.telemetry.null:NullMetrics",
    )
    try:
        assert resolve_adapter("fake-adapter") is NullMetrics
    finally:
        del _ADAPTERS["fake-adapter"]
        del _CAPABILITIES["fake-adapter"]


def test__capabilities_matrix__contains_all_adapters_without_importing_sdk() -> None:
    matrix = clientwright.capabilities_matrix()
    assert matrix["httpx"].seam == "transport"
    assert matrix["httpx2"].seam == "transport"
    assert matrix["aiohttp"].seam == "middleware"
    assert matrix["requests"].seam == "http_adapter"
    assert matrix["urllib3"].seam == "urlopen"
