"""requests adapter (``[requests]`` extra): real Session, engine underneath.

SDK-backed names resolve lazily (see ``clientwright.adapters._lazy``): importing
this package never imports requests, so the capabilities matrix stays
extras-free. The per-call channel comes from the zero-dependency core and is
therefore eager.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...core.options import CallOptions as CallOptions
from ...core.options import call_options as call_options
from .._lazy import lazy_attribute

if TYPE_CHECKING:
    from .adapter import RequestsAdapter as RequestsAdapter
    from .capabilities import CAPABILITIES as CAPABILITIES
    from .errors import RequestsCircuitOpenError as RequestsCircuitOpenError
    from .errors import RequestsDeadlineExceededError as RequestsDeadlineExceededError
    from .errors import RequestsTooManyRedirectsError as RequestsTooManyRedirectsError

_EXPORTS = {
    "CAPABILITIES": "capabilities",
    "RequestsAdapter": "adapter",
    "RequestsCircuitOpenError": "errors",
    "RequestsDeadlineExceededError": "errors",
    "RequestsTooManyRedirectsError": "errors",
}


def __getattr__(name: str) -> Any:
    return lazy_attribute(__name__, globals(), _EXPORTS, name)


__all__ = [
    "CAPABILITIES",
    "CallOptions",
    "RequestsAdapter",
    "RequestsCircuitOpenError",
    "RequestsDeadlineExceededError",
    "RequestsTooManyRedirectsError",
    "call_options",
]
