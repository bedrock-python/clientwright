"""urllib3 normalizer: discard resilience and honestly absent conn metrics."""

from __future__ import annotations

import pytest

urllib3 = pytest.importorskip("urllib3", reason="requires the [urllib3] extra")

from clientwright.adapters.urllib3.normalize import SyncUrllib3Normalizer  # noqa: E402


def test__discard__drains_the_connection_back_to_the_pool() -> None:
    drained: list[bool] = []

    class _Response:
        def drain_conn(self) -> None:
            drained.append(True)

    normalizer = SyncUrllib3Normalizer()
    assert normalizer.discard(normalizer.wrap_response(_Response())) is None
    assert drained == [True]


def test__discard__swallows_a_failing_drain() -> None:
    class _Response:
        def drain_conn(self) -> None:
            raise RuntimeError("connection already gone")

    normalizer = SyncUrllib3Normalizer()
    assert normalizer.discard(normalizer.wrap_response(_Response())) is None


def test__conn_metrics__honestly_absent() -> None:
    normalizer = SyncUrllib3Normalizer()
    view = normalizer.wrap_response(urllib3.HTTPResponse(body=b"", status=200, headers={}))
    assert normalizer.conn_metrics(view) is None
