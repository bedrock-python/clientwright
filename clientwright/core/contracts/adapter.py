"""Adapter contract and the dependency bundle handed to builders."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..capabilities import AdapterCapabilities
from ..config import ClientConfig
from .context import DeadlineSource, HeaderProvider
from .observability import ClientMetricsProtocol, TracerProtocol

if TYPE_CHECKING:
    from ..plan import ClientHandle, ClientRuntime


@dataclass(frozen=True, slots=True)
class AdapterDeps:
    """Everything a service may inject; every field has a working default.

    ``runtime`` deserves APP scope in DI: circuits, retry budgets and semaphores
    must outlive REQUEST-scoped clients or they are dead code.
    """

    metrics: ClientMetricsProtocol | None = None
    tracer: TracerProtocol | None = None
    header_providers: tuple[HeaderProvider, ...] = ()
    deadline_source: DeadlineSource | None = None
    runtime: ClientRuntime | None = None
    clock: Callable[[], float] | None = None


@runtime_checkable
class ClientAdapter(Protocol):
    """One HTTP client framework, wired under its public API.

    ``native_slots`` names the slots accepted in ``NativeOptions``;
    ``reserved_keys`` maps slot -> keys the kit owns (with a hint how to get the
    same effect legally); ``allowed_keys`` maps slot -> explicit allowlist or
    ``None`` to validate against the constructor signature.
    """

    name: str
    capabilities: AdapterCapabilities
    native_slots: frozenset[str]
    reserved_keys: Mapping[str, Mapping[str, str]]
    allowed_keys: Mapping[str, frozenset[str] | None]

    def build_async(self, config: ClientConfig, deps: AdapterDeps) -> ClientHandle[Any]: ...

    def build_sync(self, config: ClientConfig, deps: AdapterDeps) -> ClientHandle[Any]: ...


_DEFAULT_DEPS = AdapterDeps()


def default_deps() -> AdapterDeps:
    return _DEFAULT_DEPS


__all__ = ["AdapterDeps", "ClientAdapter", "default_deps"]
