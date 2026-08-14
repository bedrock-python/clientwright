"""Compiled call plans, the APP-scope runtime and client handles."""

from __future__ import annotations

import time
import weakref
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from random import Random
from typing import Any

from .capabilities import (
    AdapterCapabilities,
    Capability,
    ConfigApplicationReport,
    Support,
    dead_retryable_kinds,
)
from .config import ClientConfig, RetryMode, resolve
from .model import FailureKind, ResolvedTimeouts
from .policy.budget import RetryBudgetRegistry
from .policy.circuit import CircuitRegistry, StateListener
from .policy.concurrency import AsyncOriginLimiter, SyncOriginLimiter
from .policy.retry import DefaultRetryPolicy
from .policy.timeout import TimeoutPlanner, base_timeouts


class ClientRuntime:
    """State that must outlive REQUEST-scoped clients: circuits, budgets, limiters.

    Give this APP scope in DI. A fresh runtime per client makes the circuit
    breaker and retry budget decorative.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        rng: Random | None = None,
        circuits: CircuitRegistry | None = None,
        retry_budgets: RetryBudgetRegistry | None = None,
        async_limiter: AsyncOriginLimiter | None = None,
        sync_limiter: SyncOriginLimiter | None = None,
    ) -> None:
        self.clock: Callable[[], float] = clock or time.monotonic
        self.rng = rng or Random()  # noqa: S311 - jitter, not cryptography
        self.circuits = circuits
        self.retry_budgets = retry_budgets
        self.async_limiter = async_limiter
        self.sync_limiter = sync_limiter

    @classmethod
    def for_config(
        cls,
        config: ClientConfig,
        *,
        clock: Callable[[], float] | None = None,
        rng: Random | None = None,
        circuit_listener: StateListener | None = None,
    ) -> ClientRuntime:
        resolved_clock = clock or time.monotonic
        circuits = (
            CircuitRegistry(config.circuit_breaker, resolved_clock, circuit_listener)
            if config.circuit_breaker is not None
            else None
        )
        retry_budgets = (
            RetryBudgetRegistry(config.retry.budget_ratio)
            if config.retry is not None and config.retry.budget_ratio is not None
            else None
        )
        per_host = resolve(config.pool.max_connections_per_host, None)
        async_limiter = AsyncOriginLimiter(per_host) if per_host is not None else None
        sync_limiter = SyncOriginLimiter(per_host) if per_host is not None else None
        return cls(
            clock=resolved_clock,
            rng=rng,
            circuits=circuits,
            retry_budgets=retry_budgets,
            async_limiter=async_limiter,
            sync_limiter=sync_limiter,
        )


@dataclass(frozen=True, slots=True)
class CallPlan:
    """Everything the engine needs, compiled once at build time."""

    config: ClientConfig
    capabilities: AdapterCapabilities
    planner: TimeoutPlanner
    retry_policy: DefaultRetryPolicy | None
    report: ConfigApplicationReport
    use_origin_limiter: bool
    # False under RetryMode.DELEGATED: attempts live below the seam, inside the
    # native retry machinery, and a single fake attempt record would be a lie.
    emit_attempt_metrics: bool = True


def compile_plan(
    config: ClientConfig,
    capabilities: AdapterCapabilities,
    *,
    native_timeout_defaults: ResolvedTimeouts,
    applied_natively: frozenset[Capability] = frozenset(),
    emulated: frozenset[Capability] = frozenset(),
    dropped: Mapping[Capability, str] | None = None,
    native_overrides: Mapping[str, tuple[str, ...]] | None = None,
) -> CallPlan:
    """Compile config against capabilities; the caller enforces the report."""
    dead: frozenset[FailureKind] = frozenset()
    retry_policy: DefaultRetryPolicy | None = None
    if config.retry is not None and config.retry.mode is RetryMode.OWNED:
        retry_policy = DefaultRetryPolicy(config.retry)
        dead = dead_retryable_kinds(config.retry.retryable_kinds, capabilities)
    report = ConfigApplicationReport(
        adapter=capabilities.adapter,
        applied_natively=applied_natively,
        emulated=emulated,
        dropped=dict(dropped or {}),
        dead_retryable_kinds=dead,
        collapsed_kinds=dict(capabilities.collapses),
        native_overrides=dict(native_overrides or {}),
    )
    per_host = resolve(config.pool.max_connections_per_host, None)
    use_origin_limiter = (
        per_host is not None and capabilities.support_of(Capability.POOL_LIMIT_PER_HOST) is Support.EMULATED
    )
    delegated = config.retry is not None and config.retry.mode is RetryMode.DELEGATED
    return CallPlan(
        config=config,
        capabilities=capabilities,
        planner=TimeoutPlanner(base_timeouts(config.timeout, native_timeout_defaults), config.caller_override),
        retry_policy=retry_policy,
        report=report,
        use_origin_limiter=use_origin_limiter,
        emit_attempt_metrics=not delegated,
    )


@dataclass(slots=True)
class ClientHandle[ClientT]:
    """The real native client plus everything clientwright knows about it."""

    client: ClientT
    adapter: str
    capabilities: AdapterCapabilities
    report: ConfigApplicationReport
    runtime: ClientRuntime
    plan: CallPlan
    aclose: Callable[[], Awaitable[None]] | None = None
    close: Callable[[], None] | None = None


# The handle lives ON the client instance: the client<->handle reference cycle
# is collectable by the garbage collector once the caller drops both, unlike a
# module-global registry whose strong value would pin the client forever.
_HANDLE_ATTRIBUTE = "_clientwright_handle"

# Fallback for exotic clients without __dict__; entries here live as long as
# the handle does, which is as long as the client (documented limitation).
_HANDLE_FALLBACK: weakref.WeakKeyDictionary[Any, ClientHandle[Any]] = weakref.WeakKeyDictionary()


def register_handle(client: object, handle: ClientHandle[Any]) -> None:
    try:
        object.__setattr__(client, _HANDLE_ATTRIBUTE, handle)
    except (AttributeError, TypeError):
        _HANDLE_FALLBACK[client] = handle


def inspect_client(client: object) -> ClientHandle[Any] | None:
    """The handle of a built client, or None for foreign objects."""
    handle = getattr(client, _HANDLE_ATTRIBUTE, None)
    if handle is not None:
        return handle  # type: ignore[no-any-return]
    try:
        return _HANDLE_FALLBACK.get(client)
    except TypeError:  # not weak-referenceable: certainly not a client we built
        return None


__all__ = [
    "CallPlan",
    "ClientHandle",
    "ClientRuntime",
    "compile_plan",
    "inspect_client",
    "register_handle",
]
