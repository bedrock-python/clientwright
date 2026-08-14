"""Per-call options channel for aiohttp.

aiohttp has no analogue of ``httpx.Request.extensions``: nothing the caller
passes to ``session.get(...)`` reaches a middleware. The route template and
idempotency override therefore travel through the shared core ContextVar
channel; this module re-exports it under the adapter's public path.

    with call_options(route="/users/{id}", idempotent=True):
        await session.post(f"/users/{user_id}")
"""

from __future__ import annotations

from ...core.options import CallOptions, call_options, current_call_options

__all__ = ["CallOptions", "call_options", "current_call_options"]
