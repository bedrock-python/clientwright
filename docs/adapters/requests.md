# requests

The sync workhorse. The engine mounts as a `requests.adapters.HTTPAdapter` on a
genuine `requests.Session` — the seam requests itself designed for exactly this
kind of extension:

```python
import requests
from clientwright import ClientConfig, build_sync

session = build_sync("requests", ClientConfig(service_name="reports"))
assert type(session) is requests.Session

response = session.get("https://api.example.com/reports/42")
```

## No `base_url` — on purpose

requests has no base-URL concept, and inventing one above the session would be a
wrapper — the thing clientwright refuses to be. Configs for this adapter leave
`base_url` unset and call sites use absolute URLs, exactly as idiomatic requests
code always has. (Setting `base_url` anyway fails the build with a clear error.)

## The famous timeout hole, closed

Stock requests has **no default timeout** — a bare `session.get(url)` can hang
forever, and "always pass `timeout=`" is a convention that survives until the
first forgotten call site. Under clientwright the engine plans a per-attempt
`(connect, read)` timeout from your config and the remaining total on *every*
request, so the hole is simply gone:

```python
config = ClientConfig(service_name="reports", timeout=TimeoutConfig(total=15.0))
session = build_sync("requests", config)
session.get("https://api.example.com/slow-report")  # no timeout= needed: capped at 15 s
```

A caller-passed `timeout=` still participates per your
[`caller_override`](../guide/timeouts.md#when-the-caller-also-passes-a-timeout)
mode — clamped by the total either way.

## Per-call options

```python
from clientwright.adapters.requests import call_options

with call_options(route="/reports/{id}", idempotent=True):
    session.post(url, json=payload)
```

## Capability notes

- **Deadline: soft.** Sync runtime — phase clamping plus boundary checks, honest
  `read_timeout` outcome when a stall eats the budget. Declared as
  `DEADLINE_HARD: absent`.
- **requests sits on urllib3.** The adapter suppresses the inner layer's
  instrumentation, so a requests call counts once even though urllib3 physically
  carries it — and urllib3's own hidden retry machinery is pinned off
  (`max_retries=Retry(0)`); the engine is the only retry loop.
- **HTTP/2: absent.** requests is HTTP/1.1; asking for `http2=True` lands in
  `report.dropped` (and fails a `strict` build).
- **Pool-acquire timeout: absent** — declared dropped, with the engine's
  per-origin limiter available as the emulated alternative for per-host capping.
- **mTLS with an encrypted key**: requests cannot take a key password; the
  three-element `cert` tuple is rejected at build rather than passed to a
  library that would ignore the password.
- **Errors**: `RequestsCircuitOpenError` and friends inherit
  `requests.RequestException` — existing handlers keep catching.
