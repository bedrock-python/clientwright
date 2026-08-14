"""Fixtures for the live suite: real endpoints on the public internet.

Opt-in only (``pytest --live``). The in-process ``OriginServer`` proves
semantics deterministically; these tests answer a different question - does the
whole stack behave against real TLS, real DNS, real proxies-in-the-middle and
real servers that were not written by us.
"""

from __future__ import annotations

import os

import pytest

from clientwright.core.capabilities import AdapterCapabilities, capabilities_matrix
from clientwright.core.model import FailureKind

# A stable httpbin-compatible endpoint. Override to self-host and stop depending
# on someone else's uptime: CLIENTWRIGHT_LIVE_HTTPBIN=http://localhost:8080
HTTPBIN = os.environ.get("CLIENTWRIGHT_LIVE_HTTPBIN", "https://httpbingo.org").rstrip("/")

# RFC 2606 reserves .invalid: resolvers must fail, no innocent host is bothered.
UNRESOLVABLE = "https://clientwright-live-probe.invalid"

USER_AGENT = "clientwright-live-tests (+https://github.com/bedrock-python/clientwright)"


class LiveOrigin:
    """Duck-typed stand-in for OriginServer where only ``.url`` is used."""

    def __init__(self, url: str) -> None:
        self.url = url


@pytest.fixture
def httpbin() -> LiveOrigin:
    return LiveOrigin(HTTPBIN)


# Driver names carry the flavor; capability records are keyed by adapter name.
_REGISTRY_NAME = {"httpx-sync": "httpx"}


def capabilities_of(driver_name: str) -> AdapterCapabilities:
    return capabilities_matrix()[_REGISTRY_NAME.get(driver_name, driver_name)]


def expected_outcome(capabilities: AdapterCapabilities, kind: FailureKind) -> str:
    """The label this adapter DECLARES it would produce for ``kind``.

    Live failures are the honest test of the capability record: an adapter that
    claims it can emit ``dns_error`` has to actually do it against a real
    NXDOMAIN, and one that declares the kind collapsed has to produce the
    coarser label instead.
    """
    if kind in capabilities.emits:
        return kind.value
    return capabilities.collapses.get(kind, kind).value
