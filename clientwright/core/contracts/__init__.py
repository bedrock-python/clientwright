"""The entire contract surface of the kernel: pure protocols, no SDKs."""

from .adapter import AdapterDeps as AdapterDeps
from .adapter import ClientAdapter as ClientAdapter
from .context import DeadlineSource as DeadlineSource
from .context import HeaderProvider as HeaderProvider
from .message import AsyncNormalizer as AsyncNormalizer
from .message import RequestView as RequestView
from .message import ResponseView as ResponseView
from .message import SyncNormalizer as SyncNormalizer
from .observability import ClientMetricsProtocol as ClientMetricsProtocol
from .observability import SpanProtocol as SpanProtocol
from .observability import TracerProtocol as TracerProtocol
from .settings import CircuitBreakerSettingsProtocol as CircuitBreakerSettingsProtocol
from .settings import ClientSettingsProtocol as ClientSettingsProtocol
from .settings import RetrySettingsProtocol as RetrySettingsProtocol

__all__ = [
    "AdapterDeps",
    "AsyncNormalizer",
    "CircuitBreakerSettingsProtocol",
    "ClientAdapter",
    "ClientMetricsProtocol",
    "ClientSettingsProtocol",
    "DeadlineSource",
    "HeaderProvider",
    "RequestView",
    "ResponseView",
    "RetrySettingsProtocol",
    "SpanProtocol",
    "SyncNormalizer",
    "TracerProtocol",
]
