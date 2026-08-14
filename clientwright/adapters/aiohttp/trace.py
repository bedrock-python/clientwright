"""TraceConfig: the observability that survives a bypassed middleware.

Per-request ``middlewares=()`` REPLACES session middlewares - the official
cookbook even teaches the pattern - but ``trace_configs`` cannot be overridden
per request. Two things therefore live here and only here:

- the ``uninstrumented_calls_total`` sentinel: a request that starts while the
  engine middleware is NOT on the stack has bypassed every policy and metric;
- connection-level timings (DNS, connect, pool wait, connection reuse) that no
  middleware can see.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from ...core.model import ConnMetrics
from ...core.telemetry.emitter import ClientTelemetry
from ._imports import aiohttp

# True while the engine middleware is running in this task; TraceConfig reads
# it to detect requests that bypassed the seam.
ENGINE_ACTIVE: ContextVar[bool] = ContextVar("clientwright_aiohttp_engine_active", default=False)


@dataclass(slots=True)
class _ConnTrace:
    dns_started: float | None = None
    dns: float | None = None
    connect_started: float | None = None
    connect: float | None = None
    queued_started: float | None = None
    pool_wait: float | None = None
    reused: bool | None = None


# Trace callbacks run in the requesting task, so a plain ContextVar correlates
# them with the response the normalizer later reads conn metrics for.
_CONN_TRACE: ContextVar[_ConnTrace | None] = ContextVar("clientwright_aiohttp_conn_trace", default=None)


def current_conn_metrics() -> ConnMetrics | None:
    trace = _CONN_TRACE.get()
    if trace is None:
        return None
    return ConnMetrics(dns=trace.dns, connect=trace.connect, pool_wait=trace.pool_wait, reused=trace.reused)


def build_trace_config(telemetry: ClientTelemetry, clock: Callable[[], float]) -> aiohttp.TraceConfig:
    trace_config = aiohttp.TraceConfig()

    async def on_request_start(session: aiohttp.ClientSession, ctx: SimpleNamespace, params: Any) -> None:
        if not ENGINE_ACTIVE.get():
            telemetry.uninstrumented_call()
        _CONN_TRACE.set(_ConnTrace())

    async def on_dns_start(session: aiohttp.ClientSession, ctx: SimpleNamespace, params: Any) -> None:
        trace = _CONN_TRACE.get()
        if trace is not None:
            trace.dns_started = clock()

    async def on_dns_end(session: aiohttp.ClientSession, ctx: SimpleNamespace, params: Any) -> None:
        trace = _CONN_TRACE.get()
        if trace is not None and trace.dns_started is not None:
            trace.dns = clock() - trace.dns_started

    async def on_connect_start(session: aiohttp.ClientSession, ctx: SimpleNamespace, params: Any) -> None:
        trace = _CONN_TRACE.get()
        if trace is not None:
            trace.connect_started = clock()

    async def on_connect_end(session: aiohttp.ClientSession, ctx: SimpleNamespace, params: Any) -> None:
        trace = _CONN_TRACE.get()
        if trace is not None:
            trace.reused = False
            if trace.connect_started is not None:
                trace.connect = clock() - trace.connect_started

    async def on_reuseconn(session: aiohttp.ClientSession, ctx: SimpleNamespace, params: Any) -> None:
        trace = _CONN_TRACE.get()
        if trace is not None:
            trace.reused = True

    async def on_queued_start(session: aiohttp.ClientSession, ctx: SimpleNamespace, params: Any) -> None:
        trace = _CONN_TRACE.get()
        if trace is not None:
            trace.queued_started = clock()

    async def on_queued_end(session: aiohttp.ClientSession, ctx: SimpleNamespace, params: Any) -> None:
        trace = _CONN_TRACE.get()
        if trace is not None and trace.queued_started is not None:
            trace.pool_wait = clock() - trace.queued_started

    trace_config.on_request_start.append(on_request_start)
    trace_config.on_dns_resolvehost_start.append(on_dns_start)
    trace_config.on_dns_resolvehost_end.append(on_dns_end)
    trace_config.on_connection_create_start.append(on_connect_start)
    trace_config.on_connection_create_end.append(on_connect_end)
    trace_config.on_connection_reuseconn.append(on_reuseconn)
    trace_config.on_connection_queued_start.append(on_queued_start)
    trace_config.on_connection_queued_end.append(on_queued_end)
    return trace_config


__all__ = ["ENGINE_ACTIVE", "build_trace_config", "current_conn_metrics"]
