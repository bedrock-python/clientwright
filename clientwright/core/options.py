"""Ambient per-call options for adapters without a native per-request channel.

httpx carries route/idempotency in ``request.extensions``; aiohttp, requests
and urllib3 have no such container, so the options travel through a ContextVar
set by the caller around the call. A task or thread-local context started
under ``call_options`` inherits it; siblings do not.

    with call_options(route="/users/{id}", idempotent=True):
        session.post(f"/users/{user_id}")

One shared channel on purpose: the block applies to whichever clientwright
client sends inside it, uniformly across adapters.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CallOptions:
    route: str | None = None
    idempotent: bool | None = None


_CALL_OPTIONS: ContextVar[CallOptions | None] = ContextVar("clientwright_call_options", default=None)


def current_call_options() -> CallOptions | None:
    return _CALL_OPTIONS.get()


@contextmanager
def call_options(*, route: str | None = None, idempotent: bool | None = None) -> Generator[CallOptions]:
    options = CallOptions(route=route, idempotent=idempotent)
    token = _CALL_OPTIONS.set(options)
    try:
        yield options
    finally:
        _CALL_OPTIONS.reset(token)


__all__ = ["CallOptions", "call_options", "current_call_options"]
