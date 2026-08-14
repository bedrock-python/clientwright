"""aiohttp adapter (``[aiohttp]`` extra): real ClientSession, engine underneath.

Names resolve lazily (see ``clientwright.adapters._lazy``): importing this
package never imports aiohttp, so the capabilities matrix stays extras-free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .._lazy import lazy_attribute

if TYPE_CHECKING:
    from .adapter import AiohttpAdapter as AiohttpAdapter
    from .capabilities import CAPABILITIES as CAPABILITIES
    from .errors import AiohttpCircuitOpenError as AiohttpCircuitOpenError
    from .errors import AiohttpDeadlineExceededError as AiohttpDeadlineExceededError
    from .errors import AiohttpTooManyRedirectsError as AiohttpTooManyRedirectsError
    from .options import CallOptions as CallOptions
    from .options import call_options as call_options

_EXPORTS = {
    "CAPABILITIES": "capabilities",
    "AiohttpAdapter": "adapter",
    "AiohttpCircuitOpenError": "errors",
    "AiohttpDeadlineExceededError": "errors",
    "AiohttpTooManyRedirectsError": "errors",
    "CallOptions": "options",
    "call_options": "options",
}


def __getattr__(name: str) -> Any:
    return lazy_attribute(__name__, globals(), _EXPORTS, name)


__all__ = [
    "CAPABILITIES",
    "AiohttpAdapter",
    "AiohttpCircuitOpenError",
    "AiohttpDeadlineExceededError",
    "AiohttpTooManyRedirectsError",
    "CallOptions",
    "call_options",
]
