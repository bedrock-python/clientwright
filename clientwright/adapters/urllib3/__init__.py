"""urllib3 adapter (``[urllib3]`` extra): real PoolManager, engine underneath.

SDK-backed names resolve lazily (see ``clientwright.adapters._lazy``): importing
this package never imports urllib3, so the capabilities matrix stays
extras-free. The per-call channel comes from the zero-dependency core and is
therefore eager.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...core.options import CallOptions as CallOptions
from ...core.options import call_options as call_options
from .._lazy import lazy_attribute

if TYPE_CHECKING:
    from .adapter import Urllib3Adapter as Urllib3Adapter
    from .adapter import translate_retry as translate_retry
    from .capabilities import CAPABILITIES as CAPABILITIES
    from .errors import Urllib3CircuitOpenError as Urllib3CircuitOpenError
    from .errors import Urllib3DeadlineExceededError as Urllib3DeadlineExceededError
    from .errors import Urllib3TooManyRedirectsError as Urllib3TooManyRedirectsError

_EXPORTS = {
    "CAPABILITIES": "capabilities",
    "Urllib3Adapter": "adapter",
    "Urllib3CircuitOpenError": "errors",
    "Urllib3DeadlineExceededError": "errors",
    "Urllib3TooManyRedirectsError": "errors",
    "translate_retry": "adapter",
}


def __getattr__(name: str) -> Any:
    return lazy_attribute(__name__, globals(), _EXPORTS, name)


__all__ = [
    "CAPABILITIES",
    "CallOptions",
    "Urllib3Adapter",
    "Urllib3CircuitOpenError",
    "Urllib3DeadlineExceededError",
    "Urllib3TooManyRedirectsError",
    "call_options",
    "translate_retry",
]
