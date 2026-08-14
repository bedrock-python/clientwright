"""Property invariants of header and URL redaction."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit

from hypothesis import given
from hypothesis import strategies as st

from clientwright.core.config import DEFAULT_SENSITIVE_HEADERS, DEFAULT_SENSITIVE_QUERY_PARAMS
from clientwright.core.telemetry.redaction import REDACTED, redact_headers, redact_url

header_names = st.one_of(
    st.sampled_from(sorted(DEFAULT_SENSITIVE_HEADERS)),
    st.text(alphabet="abcdefghij-", min_size=1, max_size=12),
)
secret_values = st.text(alphabet="0123456789abcdef", min_size=8, max_size=16).map(lambda s: f"sekret{s}")


@given(headers=st.dictionaries(header_names, secret_values, max_size=8))
def test__headers__keys_preserved_and_split_exactly_by_sensitivity(headers: dict[str, str]) -> None:
    redacted = redact_headers(headers, DEFAULT_SENSITIVE_HEADERS)
    assert set(redacted) == set(headers)
    for name, value in headers.items():
        if name.lower() in DEFAULT_SENSITIVE_HEADERS:
            assert redacted[name] == REDACTED
        else:
            assert redacted[name] == value


@given(headers=st.dictionaries(header_names, secret_values, max_size=8))
def test__headers__redaction_is_idempotent(headers: dict[str, str]) -> None:
    once = redact_headers(headers, DEFAULT_SENSITIVE_HEADERS)
    assert redact_headers(once, DEFAULT_SENSITIVE_HEADERS) == once


param_names = st.one_of(
    st.sampled_from(sorted(DEFAULT_SENSITIVE_QUERY_PARAMS)),
    st.text(alphabet="abcdefghij", min_size=1, max_size=10),
)


def _uniquify(params: dict[str, str]) -> dict[str, str]:
    """Distinct, non-substring values per key so 'value survived' checks cannot alias."""
    return {name: f"{value}-k{index:02d}-end" for index, (name, value) in enumerate(sorted(params.items()))}


@given(params=st.dictionaries(param_names, secret_values, max_size=8).map(_uniquify))
def test__url__sensitive_values_never_survive_and_the_rest_is_untouched(params: dict[str, str]) -> None:
    url = "https://api.example.com/v1/things?" + urlencode(params)
    redacted = redact_url(url, DEFAULT_SENSITIVE_QUERY_PARAMS)
    parts = urlsplit(redacted)
    assert parts.scheme == "https"
    assert parts.netloc == "api.example.com"
    assert parts.path == "/v1/things"
    surviving = dict(parse_qsl(parts.query))
    assert set(surviving) == set(params)  # parameter NAMES always survive
    for name, value in params.items():
        if name.lower() in DEFAULT_SENSITIVE_QUERY_PARAMS:
            assert value not in redacted  # the secret itself is gone
        else:
            assert surviving[name] == value
