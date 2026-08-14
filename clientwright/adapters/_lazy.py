"""Lazy re-exports for adapter packages.

Importing an adapter package must NOT import its SDK. The registry reaches
``<adapter>.capabilities`` *through* the package, and Python executes a
package's ``__init__`` before any submodule of it - so an eager
``from .adapter import ...`` there would drag the SDK in and break
``capabilities_matrix()`` on a bare install, which is exactly the promise the
zero-dependency core exists to keep.

Each adapter therefore maps its public names to submodules and resolves them on
first attribute access; the SDK's install hint surfaces then, not at import.
"""

from __future__ import annotations

import importlib
from typing import Any


def lazy_attribute(package: str, namespace: dict[str, Any], exports: dict[str, str], name: str) -> Any:
    """Resolve ``name`` from its submodule and cache it in the package namespace."""
    submodule = exports.get(name)
    if submodule is None:
        raise AttributeError(f"module {package!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f".{submodule}", package), name)
    namespace[name] = value
    return value


__all__ = ["lazy_attribute"]
