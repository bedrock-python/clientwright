"""httpx adapter (``[httpx]`` extra): real httpx clients, engine underneath.

Names resolve lazily (see ``clientwright.adapters._lazy``): importing this
package never imports httpx, so the capabilities matrix stays extras-free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .._lazy import lazy_attribute

if TYPE_CHECKING:
    from .adapter import HttpxAdapter as HttpxAdapter
    from .capabilities import CAPABILITIES as CAPABILITIES
    from .errors import HttpxCircuitOpenError as HttpxCircuitOpenError
    from .errors import HttpxDeadlineExceededError as HttpxDeadlineExceededError
    from .errors import HttpxTooManyRedirectsError as HttpxTooManyRedirectsError
    from .views import IDEMPOTENT_EXTENSION as IDEMPOTENT_EXTENSION
    from .views import ROUTE_EXTENSION as ROUTE_EXTENSION

_EXPORTS = {
    "CAPABILITIES": "capabilities",
    "HttpxAdapter": "adapter",
    "HttpxCircuitOpenError": "errors",
    "HttpxDeadlineExceededError": "errors",
    "HttpxTooManyRedirectsError": "errors",
    "IDEMPOTENT_EXTENSION": "views",
    "ROUTE_EXTENSION": "views",
}


def __getattr__(name: str) -> Any:
    return lazy_attribute(__name__, globals(), _EXPORTS, name)


__all__ = [
    "CAPABILITIES",
    "IDEMPOTENT_EXTENSION",
    "ROUTE_EXTENSION",
    "HttpxAdapter",
    "HttpxCircuitOpenError",
    "HttpxDeadlineExceededError",
    "HttpxTooManyRedirectsError",
]
