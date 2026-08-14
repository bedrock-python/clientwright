"""The target-resolution seam: a protocol only, deliberately without implementations."""

from __future__ import annotations

from collections.abc import Sequence

from clientwright.core.balancer.policy import TargetResolverProtocol
from clientwright.core.model import Attempt, RequestInfo


class RoundRobinish:
    def __init__(self, targets: list[str]) -> None:
        self._targets = targets

    def pick(self, info: RequestInfo, history: Sequence[Attempt]) -> str:
        return self._targets[len(history) % len(self._targets)]


def test__structural_resolver__satisfies_the_protocol() -> None:
    resolver = RoundRobinish(["http://a:80", "http://b:80"])
    assert isinstance(resolver, TargetResolverProtocol)
    info = RequestInfo(method="GET", origin="http://a:80", url="http://a/x")
    assert resolver.pick(info, []) == "http://a:80"


def test__object_without_pick__rejected() -> None:
    assert not isinstance(object(), TargetResolverProtocol)
