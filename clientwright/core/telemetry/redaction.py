"""Secret redaction for logs and spans."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[redacted]"


def redact_headers(headers: Mapping[str, str], sensitive: frozenset[str]) -> dict[str, str]:
    return {name: (REDACTED if name.lower() in sensitive else value) for name, value in headers.items()}


def redact_url(url: str, sensitive_params: frozenset[str]) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    cleaned = [(name, REDACTED if name.lower() in sensitive_params else value) for name, value in pairs]
    return urlunsplit(parts._replace(query=urlencode(cleaned)))


__all__ = ["REDACTED", "redact_headers", "redact_url"]
