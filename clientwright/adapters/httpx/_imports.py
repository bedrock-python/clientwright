"""Lazy import guard for the optional httpx stack.

Importing this module fails with a friendly message when the ``httpx`` extra is
not installed, so ``import clientwright`` never pays the cost (or the failure).
Every httpx submodule imports its third-party symbols from here.
"""

from __future__ import annotations

_INSTALL_HINT = "httpx support requires clientwright[httpx]; install it."

try:
    import httpx
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(_INSTALL_HINT) from exc

__all__ = ["httpx"]
