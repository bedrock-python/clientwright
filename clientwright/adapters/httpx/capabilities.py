"""httpx capability declaration. Zero-dependency: never imports httpx."""

from __future__ import annotations

from .._httpx_shared import capabilities_for

CAPABILITIES = capabilities_for("httpx")

__all__ = ["CAPABILITIES"]
