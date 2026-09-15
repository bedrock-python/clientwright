"""contrib units: the servicewright header providers."""

from __future__ import annotations

import pytest

servicewright = pytest.importorskip("servicewright", reason="requires the [servicewright] extra")

from clientwright import HeaderProvider  # noqa: E402
from clientwright.contrib.servicewright import servicewright_headers  # noqa: E402


def test__providers__are_the_bare_function_and_satisfy_the_protocol() -> None:
    providers = servicewright_headers()
    assert providers == (servicewright.propagation_metadata,)
    assert all(isinstance(provider, HeaderProvider) for provider in providers)


def test__provider__reads_the_bound_context_and_nothing_outside_it() -> None:
    (provider,) = servicewright_headers()
    with servicewright.bind_context(request_id="rid-1", user_id="u-9"):
        assert provider() == {"x-request-id": "rid-1", "x-user-id": "u-9"}
    assert provider() == {}
