"""Machine-readable declarations of what each adapter can and cannot do.

Uniformity is sold by policy and telemetry schema, not by pretending semantics
match: every divergence is declared here, validated at build time, and visible
in the ``ConfigApplicationReport`` instead of a README paragraph.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from .config import UnsupportedPolicy
from .errors import UnsupportedCapabilityError
from .model import FailureKind

logger = logging.getLogger("clientwright.capabilities")


class Support(StrEnum):
    NATIVE = "native"
    EMULATED = "emulated"
    DEGRADED = "degraded"
    ABSENT = "absent"


class Capability(StrEnum):
    TIMEOUT_TOTAL = "timeout_total"
    TIMEOUT_ATTEMPT = "timeout_attempt"
    TIMEOUT_CONNECT = "timeout_connect"
    TIMEOUT_READ = "timeout_read"
    TIMEOUT_WRITE = "timeout_write"
    TIMEOUT_POOL = "timeout_pool"
    DEADLINE_HARD = "deadline_hard"
    POOL_LIMIT_TOTAL = "pool_limit_total"
    POOL_LIMIT_PER_HOST = "pool_limit_per_host"
    KEEPALIVE = "keepalive"
    POOL_METRICS = "pool_metrics"
    CONN_METRICS = "conn_metrics"
    REDIRECTS_OWNABLE = "redirects_ownable"
    NATIVE_RETRY_DISABLEABLE = "native_retry_disableable"
    PER_CALL_OPTIONS = "per_call_options"
    RETROFIT = "retrofit"
    EXACT_NATIVE_TYPE = "exact_native_type"
    BALANCER = "balancer"
    HTTP2 = "http2"
    HTTP3 = "http3"
    PROXY = "proxy"


class DurationBoundary(StrEnum):
    HEADERS = "headers"
    FULL = "full"


class SeamGranularity(StrEnum):
    HOP = "hop"
    LOGICAL = "logical"


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    """Everything an adapter admits about itself, in one frozen record."""

    adapter: str
    seam: str
    granularity: SeamGranularity
    boundary: DurationBoundary
    support: Mapping[Capability, Support]
    emits: frozenset[FailureKind]
    collapses: Mapping[FailureKind, FailureKind] = field(default_factory=dict)
    notes: Mapping[str, str] = field(default_factory=dict)

    def support_of(self, capability: Capability) -> Support:
        return self.support.get(capability, Support.ABSENT)


@dataclass(frozen=True, slots=True)
class ConfigApplicationReport:
    """What actually happened when a config met an adapter."""

    adapter: str
    applied_natively: frozenset[Capability] = frozenset()
    emulated: frozenset[Capability] = frozenset()
    dropped: Mapping[Capability, str] = field(default_factory=dict)
    dead_retryable_kinds: frozenset[FailureKind] = frozenset()
    collapsed_kinds: Mapping[FailureKind, FailureKind] = field(default_factory=dict)
    native_overrides: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def has_issues(self) -> bool:
        return bool(self.dropped or self.dead_retryable_kinds)

    def issues(self) -> list[str]:
        problems = [f"{capability.value}: {reason}" for capability, reason in self.dropped.items()]
        if self.dead_retryable_kinds:
            dead = ", ".join(sorted(kind.value for kind in self.dead_retryable_kinds))
            problems.append(f"retryable_kinds never emitted by {self.adapter}: {dead}")
        return problems

    def enforce(self, policy: UnsupportedPolicy) -> None:
        """Apply the on_unsupported policy: raise, warn or stay silent."""
        if not self.has_issues or policy is UnsupportedPolicy.IGNORE:
            return
        problems = self.issues()
        if policy is UnsupportedPolicy.STRICT:
            raise UnsupportedCapabilityError(
                f"Adapter {self.adapter!r} cannot express the requested config: " + "; ".join(problems)
            )
        for problem in problems:
            logger.warning("Adapter %s: %s", self.adapter, problem)


def dead_retryable_kinds(
    requested: frozenset[FailureKind], capabilities: AdapterCapabilities
) -> frozenset[FailureKind]:
    """Kinds the retry policy waits for but the adapter can never produce.

    Collapsed kinds count as reachable through their coarser target.
    """
    reachable = set(capabilities.emits)
    for source, target in capabilities.collapses.items():
        if target in reachable:
            reachable.add(source)
    return frozenset(requested - reachable)


def capabilities_matrix() -> dict[str, AdapterCapabilities]:
    """Capability records of every registered adapter.

    Adapter capability modules are zero-dependency and are imported dynamically
    by registry path, so the matrix builds in an environment without a single
    extra installed (and the core->adapters import-linter contract holds:
    there are no static imports).
    """
    return _capability_records()


def _capability_records() -> dict[str, AdapterCapabilities]:
    from .registry import capability_records  # noqa: PLC0415 - deferred to keep module init order acyclic

    return capability_records()


__all__ = [
    "AdapterCapabilities",
    "Capability",
    "ConfigApplicationReport",
    "DurationBoundary",
    "SeamGranularity",
    "Support",
    "capabilities_matrix",
    "dead_retryable_kinds",
]
