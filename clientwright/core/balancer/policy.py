"""Target resolution seam for future client-side load balancing.

Deliberately empty of implementations: in k8s/service-mesh environments client
LB is usually harmful. The seam costs nothing because ``RequestView.retarget``
already exists for owned redirects.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ..model import Attempt, RequestInfo


@runtime_checkable
class TargetResolverProtocol(Protocol):
    """Pure target choice; no health RPCs, no I/O."""

    def pick(self, info: RequestInfo, history: Sequence[Attempt]) -> str: ...


__all__ = ["TargetResolverProtocol"]
