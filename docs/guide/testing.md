# Testing your service

clientwright ships its own test instruments under `clientwright.core.testing` —
the same ones its 500-test suite runs on. They are stdlib-only and need no
Docker, no fixtures package, no network beyond localhost.

## Unit tests: don't use clientwright at all

For unit tests of a use case, the org pattern stands: the HTTP client is an
external dependency — mock the *client object* your code receives. Because
clientwright hands out genuine native clients, every SDK mocking tool works
unchanged: `respx` for httpx, `aioresponses` for aiohttp, a `MagicMock` with the
right spec. Nothing about clientwright leaks into these tests.

## Integration tests: a fault-injecting origin

When you want the real engine against real sockets, `OriginServer` is an
in-process HTTP server on an ephemeral localhost port with fault injection built
into its routes:

```python
import pytest

import clientwright
from clientwright import ClientConfig, RetryConfig
from clientwright.core.testing import OriginServer


@pytest.fixture
def origin():
    with OriginServer() as server:
        yield server


async def test__flaky_upstream__is_retried(origin: OriginServer) -> None:
    config = ClientConfig(
        service_name="test",
        base_url=origin.url,
        retry=RetryConfig(max_attempts=3, initial_backoff=0.01, jitter=0.0),
    )
    client = clientwright.build("httpx", config)
    response = await client.get("/flaky/case1/2")  # 503 twice, then 200
    assert response.status_code == 200
    assert origin.request_count("/flaky/case1/2") == 3
    await client.aclose()
```

The route table reads like a chaos menu:

| Route | Behavior |
|---|---|
| `/echo` | 200 with method, path and headers echoed as JSON |
| `/status/{code}` | that status |
| `/slow/{seconds}` | stalls before answering |
| `/flaky/{key}/{fails}` | first *fails* requests per key answer 503, then 200 |
| `/flaky-disconnect/{key}/{fails}` | same, but drops the connection instead |
| `/retry-after/{seconds}` | 503 with a `Retry-After` header |
| `/redirect/{n}` | a 302 chain of *n* hops |
| `/redirect-loop` | 302 to itself forever |
| `/disconnect` | closes without a response |
| `/drop-body` | announces 10 body bytes, dies after 3 |
| `/hang-body/{seconds}` | sends 3 bytes, stalls, then finishes |
| `/garbage` | raw non-HTTP bytes instead of a status line |
| `/reset` | a hard TCP reset |

`origin.requests` records every `(method, path)` the server saw;
`origin.request_count(prefix)` is the assertion helper you will actually use.

## Asserting on telemetry

`RecordingMetrics` implements the metrics protocol and remembers everything:

```python
from clientwright import AdapterDeps
from clientwright.core.testing import RecordingMetrics

metrics = RecordingMetrics()
client = clientwright.build("httpx", config, AdapterDeps(metrics=metrics))

# ... make calls ...

assert [call["outcome"] for call in metrics.calls] == ["success"]
assert len(metrics.attempts) == 3  # the retries, visible
assert metrics.inflight_balance == 0  # every start matched an end
```

`metrics.retry_skips`, `metrics.circuit_states` and `metrics.redirect_hops` cover
the rest of the schema. If your test cares about deterministic time,
`ManualClock` is a monotonic clock you advance by hand — `ClientRuntime`
accepts it via `ClientRuntime.for_config(config, clock=clock)`.

## Two sharp tools

**`suppressed()`** — a context manager that makes clientwright's instrumentation
stand down for the calls inside it. The engine's own layering uses it (requests
over urllib3 must not double-count); in tests it is occasionally useful to make
a raw control-call that should not appear in metrics:

```python
from clientwright.core.engine.suppress import suppressed

with suppressed():
    manager.request("GET", origin.url + "/echo")  # native path, no telemetry
```

**Skipping without an extra** — if your test module imports an SDK-specific
piece, guard it the way clientwright's own suite does:

```python
httpx = pytest.importorskip("httpx", reason="requires the [httpx] extra")
```
