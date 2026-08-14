# Circuit breaker

Retries protect one call. The circuit breaker protects everything else: when an
upstream is genuinely down, continuing to send it traffic makes your latency worse
and its recovery slower. The breaker notices, fails fast locally for a while, then
probes.

## The config

```python
from clientwright import CircuitBreakerConfig, ClientConfig

config = ClientConfig(
    service_name="orders",
    circuit_breaker=CircuitBreakerConfig(
        fail_threshold=5,  # consecutive qualifying failures to open
        recovery_timeout=60.0,  # seconds open before probing
        half_open_max_calls=1,  # concurrent probes allowed while half-open
    ),
)
```

On by default; `circuit_breaker=None` disables. State lives in the
[`ClientRuntime`](dishka.md) — which is why the runtime must be application-scoped:
a breaker that is recreated per request has no memory and therefore no function.

## One signal per logical call

A subtle rule with big consequences: the breaker hears about each *logical call*
exactly once, with its **final** outcome. A call that failed twice and succeeded on
the third attempt is one success — retries can never pump the failure counter on
their own. (The legacy pattern of counting every attempt turns a modest blip into
an open circuit; clientwright counts what the caller actually experienced.)

What counts as a failure is a list of failure kinds (`trip_kinds`) covering
timeouts, connect/TLS/DNS errors, disconnects and protocol errors — plus `5xx`
responses. A `404` or a `429` never trips the breaker: the upstream is alive and
answering, just not the way you hoped.

Cancelled calls are a third category: neither success nor failure. If the caller
gave up (or an ambient [deadline budget](deadline-budget.md) cancelled the task),
the engine tells the breaker to *abort* the call — releasing its half-open slot
without polluting the count in either direction.

## The state machine

```text
CLOSED --- fail_threshold failures ---> OPEN
OPEN   --- recovery_timeout passed ---> HALF_OPEN (the transitioning call IS the probe)
HALF_OPEN --- probe succeeds ---> CLOSED
HALF_OPEN --- probe fails ------> OPEN (fresh recovery_timeout)
```

While `OPEN`, calls are rejected *locally* — no connection is attempted — with a
`CircuitOpenError` that includes the time until the next probe and dual-inherits
the adapter's native error family:

```python
import httpx
from clientwright.adapters.httpx import HttpxCircuitOpenError

try:
    await client.get("/stock")
except httpx.HTTPError as error:  # your existing handler already catches it
    ...
except HttpxCircuitOpenError as error:  # or catch the specific class
    print(f"probe in {error.retry_after:.0f}s")
```

While `HALF_OPEN`, at most `half_open_max_calls` probes fly at once — including the
call that triggered the transition, which consumes a slot like any other probe.
Everyone else keeps getting fast local rejections until a probe closes the circuit.

## Choosing the key

By default the breaker keys on **origin** (`scheme://host:port`) — one upstream,
one health verdict. Two finer granularities exist:

```python
from clientwright import CircuitBreakerConfig, CircuitKey

CircuitBreakerConfig(key=CircuitKey.ORIGIN_ROUTE)  # per (origin, route template)
CircuitBreakerConfig(key=CircuitKey.ORIGIN_METHOD)  # per (origin, HTTP method)
```

`ORIGIN_ROUTE` needs the [per-call route](per-call-options.md) to be set — an
unset route buckets under `unknown`, which quietly merges endpoints back together.
The key registry is LRU-capped (`max_keys`, 512 by default), and an armed circuit —
open or half-open — is never evicted to make room; disarming a breaker by cache
pressure would be a silent lie.

## Watching it

State transitions surface as the `http_client_circuit_state` gauge
(0 closed, 1 half-open, 2 open) labelled by `key`, and every locally rejected call
appears in `http_client_requests_total` with `outcome="circuit_open"` — so an open
circuit is visible on the dashboard as a spike of instant failures, not a
mysterious drop in traffic.
