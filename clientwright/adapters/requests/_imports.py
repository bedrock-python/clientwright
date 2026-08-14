"""Lazy import guard for the optional requests stack.

Importing this module fails with a friendly message when the ``requests``
extra is not installed. Every requests submodule imports its third-party
symbols from here. urllib3 is re-exported too: requests depends on it, and the
classifier needs the underlying exception types to tell a mid-stream
disconnect from a refused connection.
"""

from __future__ import annotations

_INSTALL_HINT = "requests support requires clientwright[requests]; install it."

try:
    import requests
    import urllib3
    from requests.adapters import HTTPAdapter
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(_INSTALL_HINT) from exc

__all__ = ["HTTPAdapter", "requests", "urllib3"]
