"""Lazy import guard for the optional urllib3 stack.

Importing this module fails with a friendly message when the ``urllib3`` extra
is not installed. Every urllib3 submodule imports its third-party symbols from
here.
"""

from __future__ import annotations

_INSTALL_HINT = "urllib3 support requires clientwright[urllib3]; install it."

try:
    import urllib3
    from urllib3.util import Retry, Timeout
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(_INSTALL_HINT) from exc

__all__ = ["Retry", "Timeout", "urllib3"]
