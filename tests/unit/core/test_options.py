"""Ambient per-call options channel shared by adapters without native extensions."""

from __future__ import annotations

import pytest

from clientwright.core.options import CallOptions, call_options, current_call_options


def test__outside_any_block__nothing_is_set() -> None:
    assert current_call_options() is None


def test__inside_block__route_and_idempotency_visible() -> None:
    with call_options(route="/users/{id}", idempotent=True) as options:
        assert options == CallOptions(route="/users/{id}", idempotent=True)
        assert current_call_options() is options
    assert current_call_options() is None


def test__nesting__inner_wins_then_outer_restored() -> None:
    with call_options(route="/outer"):
        with call_options(route="/inner", idempotent=False):
            current = current_call_options()
            assert current is not None
            assert current.route == "/inner"
            assert current.idempotent is False
        restored = current_call_options()
        assert restored is not None
        assert restored.route == "/outer"
        assert restored.idempotent is None


def test__exception_inside_block__still_restores() -> None:
    with pytest.raises(RuntimeError), call_options(route="/boom"):
        raise RuntimeError("mid-call failure")
    assert current_call_options() is None
