"""Lazy import guard for the optional aiohttp stack.

Importing this module fails with a friendly message when the ``aiohttp`` extra
is not installed, so ``import clientwright`` never pays the cost (or the
failure). Every aiohttp submodule imports its third-party symbols from here.

The adapter needs aiohttp>=3.12: earlier releases have no client middleware,
which is the only seam that can mutate requests and own the retry loop.
"""

from __future__ import annotations

import inspect

_INSTALL_HINT = "aiohttp support requires clientwright[aiohttp]; install it."
_VERSION_HINT = (
    "clientwright's aiohttp adapter requires aiohttp>=3.12 (client middleware); "
    "the installed version has no 'middlewares' parameter on ClientSession."
)

try:
    import aiohttp
    from yarl import URL
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(_INSTALL_HINT) from exc

if "middlewares" not in inspect.signature(aiohttp.ClientSession.__init__).parameters:  # pragma: no cover
    raise ImportError(_VERSION_HINT)

__all__ = ["URL", "aiohttp"]
