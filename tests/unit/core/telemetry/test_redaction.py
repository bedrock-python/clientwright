"""Header and URL redaction for logs and traces."""

from __future__ import annotations

import clientwright
from clientwright.core.telemetry.redaction import REDACTED, redact_headers, redact_url


def test__sensitive_headers__masked_case_insensitively() -> None:
    redacted = redact_headers({"Authorization": "Bearer x", "Accept": "json"}, frozenset({"authorization"}))
    assert redacted["Authorization"] == REDACTED
    assert redacted["Accept"] == "json"


def test__sensitive_query_params__masked() -> None:
    url = redact_url("https://a/x?token=secret&page=2", frozenset({"token"}))
    assert "secret" not in url
    assert "page=2" in url


def test__root_export__pairs_the_default_list_with_its_redactor() -> None:
    assert clientwright.redact_headers is redact_headers
    safe = clientwright.redact_headers({"Cookie": "s=1"}, clientwright.DEFAULT_SENSITIVE_HEADERS)
    assert safe["Cookie"] == REDACTED
