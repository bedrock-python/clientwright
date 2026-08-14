# Masking PII

Name-based redaction has a blind spot. `sensitive_query_params` catches
`?token=...` because the *name* is on a list — but nobody names a query
parameter `email` when the email is sitting in the path:

```
GET /users/alex@example.com/orders      → url.full, verbatim
GET /accounts/79161234567/balance       → url.full, verbatim
```

No name list can reach those. Scrubbing them requires looking at the *value* —
and that is a policy decision clientwright refuses to make for you. What counts
as PII depends on your jurisdiction, your data classification, your tolerance
for false positives. So the library ships a seam, not a scanner.

## The seam

`ObservabilityConfig.url_masker` accepts any `(str) -> str` callable. It runs
**after** name-based query redaction, on every URL headed for a span attribute
or a log record:

```python
import re

from clientwright import ClientConfig, ObservabilityConfig

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

config = ClientConfig(
    service_name="identity",
    observability=ObservabilityConfig(url_masker=lambda url: EMAIL.sub("***", url)),
)
```

Three things the seam guarantees:

- **Order.** The masker sees the URL with sensitive query params already
  `[redacted]` — it never sees the raw token, so it cannot leak one.
- **Fail closed.** If the masker raises, the emitter publishes `[redacted]`
  instead of the URL — never the raw value — and the request itself is
  untouched. One warning is logged per client, not per call, so a broken
  masker is visible without a log storm.
- **Scope.** Only URLs pass through it. Metrics carry no URL at all — labels
  are `origin`, `route`, `method`, `status` by design — so there is nothing to
  mask on that channel.

The formal contract is `MaskerProtocol`; a lambda satisfies it structurally.

## What it costs

The masker runs 2–3 times per HTTP call (span start, log start, log end).
Budget accordingly:

| Masker | Order of cost | Hot path? |
|---|---|---|
| compiled regex | microseconds | yes |
| format-preserving (slice + checksum) | microseconds | yes |
| `phonenumbers` validation | tens of microseconds | yes, with care |
| NER model (Presidio, GLiNER, DataFog) | **milliseconds** | almost never |

`url_masker=None` (the default) costs nothing.

## Recipes

**Format-preserving card mask** — keeps enough shape to debug with:

```python
import re

CARD = re.compile(r"\b(\d{4})\d{5,11}(\d{4})\b")


def mask_cards(url: str) -> str:
    return CARD.sub(r"\1***\2", url)
```

**Composition** — maskers are just callables, so chain them with a loop:

```python
def compose(*maskers):
    def masked(url: str) -> str:
        for mask in maskers:
            url = mask(url)
        return url

    return masked
```

**Presidio** — a real NER engine, and a deliberate trade-off. Build the engine
once at process start (model load takes seconds), never per call, and put it on
low-QPS clients only — at milliseconds per invocation it does not belong on a
busy client's hot path:

```python
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

analyzer = AnalyzerEngine()  # APP scope: seconds to load, hundreds of MB
anonymizer = AnonymizerEngine()


def presidio_masker(url: str) -> str:
    results = analyzer.analyze(text=url, language="en")
    return anonymizer.anonymize(text=url, analyzer_results=results).text
```

If what you actually want is ML-grade scrubbing of *logs and error reports*
service-wide, that belongs in your service runtime's redaction seam (one
masker on the error path sees every outgoing exception at a fraction of the
call rate) — not in every HTTP client.

## Headers

clientwright never writes request or response headers into logs or spans —
that firehose is excluded by design, which is why there is no header knob on
`ObservabilityConfig`. If your *own* code logs headers, the toolkit is public:

```python
from clientwright.core.config import DEFAULT_SENSITIVE_HEADERS
from clientwright.core.telemetry.redaction import redact_headers

safe = redact_headers(response.headers, DEFAULT_SENSITIVE_HEADERS)
```
