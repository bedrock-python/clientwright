"""requests normalizer: the replayability probe, body rewind and discard resilience."""

from __future__ import annotations

import io

import pytest

requests = pytest.importorskip("requests", reason="requires the [requests] extra")

from clientwright.adapters.requests.normalize import SyncRequestsNormalizer  # noqa: E402


def _prepared_with(data: object) -> requests.PreparedRequest:
    return requests.Request("POST", "http://a.example/x", data=data).prepare()


def test__freeze__true_for_a_seekable_stream_body() -> None:
    normalizer = SyncRequestsNormalizer()
    view = normalizer.wrap_request(_prepared_with(io.BytesIO(b"payload")))
    assert normalizer.freeze(view) is True


def test__freeze__false_for_a_one_shot_generator_body() -> None:
    normalizer = SyncRequestsNormalizer()
    view = normalizer.wrap_request(_prepared_with(chunk for chunk in [b"part-1", b"part-2"]))
    assert normalizer.freeze(view) is False


def test__rewind__seeks_a_stream_body_back_to_its_start() -> None:
    normalizer = SyncRequestsNormalizer()
    stream = io.BytesIO(b"payload")
    request = _prepared_with(stream)
    stream.read()  # simulate the first attempt consuming the body
    assert stream.tell() == len(b"payload")
    view = normalizer.wrap_request(request)
    assert normalizer.rewind(view) is None
    assert stream.tell() == 0


def test__rewind__noop_for_bytes_bodies() -> None:
    normalizer = SyncRequestsNormalizer()
    view = normalizer.wrap_request(_prepared_with(b"payload"))
    assert normalizer.rewind(view) is None


def test__discard__swallows_a_failing_close() -> None:
    class _Response:
        def close(self) -> None:
            raise RuntimeError("connection already gone")

    normalizer = SyncRequestsNormalizer()
    view = normalizer.wrap_response(_Response())  # type: ignore[arg-type]
    assert normalizer.discard(view) is None


def test__discard__closes_the_native_response() -> None:
    closed: list[bool] = []

    class _Response:
        def close(self) -> None:
            closed.append(True)

    normalizer = SyncRequestsNormalizer()
    assert normalizer.discard(normalizer.wrap_response(_Response())) is None  # type: ignore[arg-type]
    assert closed == [True]


def test__conn_metrics__honestly_absent() -> None:
    normalizer = SyncRequestsNormalizer()
    view = normalizer.wrap_response(requests.Response())
    assert normalizer.conn_metrics(view) is None
