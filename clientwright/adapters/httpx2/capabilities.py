"""httpx2 capability declaration. Zero-dependency: never imports httpx2."""

from __future__ import annotations

from .._httpx_shared import capabilities_for

CAPABILITIES = capabilities_for("httpx2")

__all__ = ["CAPABILITIES"]
