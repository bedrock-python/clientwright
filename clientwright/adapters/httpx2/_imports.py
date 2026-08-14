"""Lazy import guard for the optional httpx2 stack.

httpx2 is the httpx successor maintained by Pydantic Services Inc.: a separate
distribution and import namespace with the same API surface. Importing this
module fails with a friendly message when the ``httpx2`` extra is not
installed. Every httpx2 submodule imports its third-party symbols from here.
"""

from __future__ import annotations

_INSTALL_HINT = "httpx2 support requires clientwright[httpx2]; install it."

try:
    import httpx2
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(_INSTALL_HINT) from exc

__all__ = ["httpx2"]
