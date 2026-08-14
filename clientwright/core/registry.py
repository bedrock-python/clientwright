"""Adapter registry: string names to lazy import paths.

``import clientwright`` pays nothing: adapter modules load only when resolved,
at which point the adapter's ``_imports`` guard raises a friendly install hint
if the matching extra is absent. Capability modules are zero-dependency and
always importable. Dynamic string imports keep the core->adapters import-linter
contract intact by construction.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from .errors import UnknownAdapterError

if TYPE_CHECKING:
    from .capabilities import AdapterCapabilities

_ADAPTERS: dict[str, str] = {
    "httpx": "clientwright.adapters.httpx.adapter:HttpxAdapter",
    "httpx2": "clientwright.adapters.httpx2.adapter:HttpxAdapter",
    "aiohttp": "clientwright.adapters.aiohttp.adapter:AiohttpAdapter",
    "requests": "clientwright.adapters.requests.adapter:RequestsAdapter",
    "urllib3": "clientwright.adapters.urllib3.adapter:Urllib3Adapter",
}

_CAPABILITIES: dict[str, str] = {
    "httpx": "clientwright.adapters.httpx.capabilities:CAPABILITIES",
    "httpx2": "clientwright.adapters.httpx2.capabilities:CAPABILITIES",
    "aiohttp": "clientwright.adapters.aiohttp.capabilities:CAPABILITIES",
    "requests": "clientwright.adapters.requests.capabilities:CAPABILITIES",
    "urllib3": "clientwright.adapters.urllib3.capabilities:CAPABILITIES",
}


def _load(target: str) -> Any:
    module_path, _, attribute = target.partition(":")
    module = importlib.import_module(module_path)
    return getattr(module, attribute)


def register_adapter(name: str, adapter_target: str, capabilities_target: str) -> None:
    """Register a third-party adapter: ``"module.path:Class"`` strings, lazily loaded."""
    for label, target in (("adapter", adapter_target), ("capabilities", capabilities_target)):
        if ":" not in target:
            raise ValueError(f"{label} target must look like 'module.path:Attribute', got {target!r}")
    _ADAPTERS[name] = adapter_target
    _CAPABILITIES[name] = capabilities_target


def registered_adapters() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


def resolve_adapter(name: str) -> Any:
    """Load and return the adapter class registered under ``name``."""
    try:
        target = _ADAPTERS[name]
    except KeyError:
        raise UnknownAdapterError(name, registered_adapters()) from None
    return _load(target)


def capability_records() -> dict[str, AdapterCapabilities]:
    """Capability record of every registered adapter; importable without extras."""
    return {name: _load(target) for name, target in sorted(_CAPABILITIES.items())}


__all__ = [
    "capability_records",
    "register_adapter",
    "registered_adapters",
    "resolve_adapter",
]
