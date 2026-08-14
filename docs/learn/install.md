# Installation

clientwright needs **Python 3.12+**.

The core package has zero dependencies and no adapter can work without its SDK, so
you always install at least one extra:

```bash
pip install clientwright[httpx]
```

## The extras matrix

| Extra | Pulls in | Gives you |
|---|---|---|
| `httpx` | `httpx>=0.28,<1` | the reference adapter, sync + async |
| `httpx2` | `httpx2>=2,<3` | Pydantic's httpx successor, sync + async |
| `aiohttp` | `aiohttp>=3.12,<4` | async adapter on the client-middleware seam |
| `requests` | `requests>=2.32,<3` | sync adapter on the `HTTPAdapter` seam |
| `urllib3` | `urllib3>=2.2,<3` | sync adapter; home of delegated retries |
| `metrics` | `prometheus-client` | the Prometheus metrics backend |
| `tracing` | `opentelemetry-api` | the OpenTelemetry tracing backend |
| `observability` | both of the above | shorthand for `[metrics,tracing]` |
| `deadline` | `deadline-budget` | ambient request-budget propagation |
| `dishka` | `dishka>=1.4` | the DI provider with a leak-free lifecycle |
| `all` | everything above | kitchen sink for experiments |

Extras combine the way you expect:

```bash
pip install "clientwright[httpx,observability,deadline]"
```

!!! note "Why zero dependencies in the core?"

    A bare `pip install clientwright` still imports, still builds the
    [capabilities matrix](../guide/capabilities.md), and still runs the policy code —
    that is what lets the test suite and CI verify the core in complete isolation.
    Adapters load lazily: nothing touches `httpx` until you call
    `build("httpx", ...)`, and a missing extra fails with an install hint instead of
    a bare `ImportError`.

## Version pinning

Each extra pins a major-version range of its SDK (see the table). The adapter seams
rely on documented but internal-ish integration points — the pin is what turns
"works on my machine" into a contract. If you need an SDK version outside the range,
that is an issue to open, not a pin to override.

## Checking what you have

```python
import clientwright

print(clientwright.registered_adapters())
# ('aiohttp', 'httpx', 'httpx2', 'requests', 'urllib3')

print(clientwright.capabilities_matrix()["httpx"].seam)
# 'transport' — importable even with no extras installed
```
