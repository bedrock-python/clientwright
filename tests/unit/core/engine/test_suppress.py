"""Cross-layer instrumentation suppression."""

from __future__ import annotations

from clientwright.core.engine.suppress import is_suppressed, suppressed


def test__nested_suppression__balances() -> None:
    assert not is_suppressed()
    with suppressed():
        assert is_suppressed()
        with suppressed():
            assert is_suppressed()
        assert is_suppressed()
    assert not is_suppressed()
