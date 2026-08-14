# Your first client

Five minutes, one file, everything visible. We build an httpx client for a flaky
imaginary API and watch clientwright deal with it.

## Build

```python
import httpx
from clientwright import ClientConfig, RetryConfig, TimeoutConfig, build

config = ClientConfig(
    service_name="orders",  # (1)!
    base_url="https://api.warehouse.example.com",
    timeout=TimeoutConfig(total=10.0, connect=2.0),  # (2)!
    retry=RetryConfig(max_attempts=3),  # (3)!
)

client = build("httpx", config)
```

1. The only required field. It becomes the `service` label on every metric and log
   line this client ever emits.
2. `total` is a wall-clock budget for the *whole logical call* — all attempts, all
   backoff sleeps, all redirect hops. `connect` caps one phase of one attempt.
   Anything you leave unset defers to the adapter's native default.
3. You could omit this: retries, a circuit breaker and owned redirects are on by
   default with production-shaped settings. It is spelled here so you can see it.

`build()` returns a plain `httpx.AsyncClient`. Type-check it, pass it to SDKs that
demand one, use every httpx feature — it is not a wrapper:

```python
assert type(client) is httpx.AsyncClient
```

## Call

```python
response = await client.get("/stock/widgets")
print(response.status_code)
```

If the API answers `503` twice and then recovers, this line still returns `200` —
the engine retried with jittered exponential backoff, drained and returned each
failed response's connection to the pool, and stayed inside the 10-second total.
If the API keeps failing, you get the ordinary httpx response or exception you
would have gotten anyway, and the circuit breaker starts counting.

Nothing about the *calling* code changed. That is the point: resilience is in the
client you already hold, not in a new API you have to adopt.

## Look inside

Every built client carries a handle you can inspect:

```python
from clientwright import inspect

handle = inspect(client)

print(handle.adapter)  # 'httpx'
print(handle.report.dropped)  # config the adapter could not express: {} here
print(handle.report.emulated)  # what the engine adds on top of httpx
print(handle.runtime.circuits)  # live circuit-breaker state, shared across requests
```

`handle.report` is the [capability honesty](../guide/capabilities.md) story: if you
had asked requests for HTTP/2, it would be in `dropped`, and with
`on_unsupported="strict"` the `build()` call itself would have raised.

## Close

The client is a native client, so its lifecycle is the native one:

```python
await client.aclose()
```

In a real service you will not manage that by hand — the
[dishka provider](../guide/dishka.md) builds the client at APP scope and closes it
with the container, which is also what keeps circuit-breaker state alive across
requests.

## Where next

- [Sync and async](sync-and-async.md) — the same machine behind `httpx.Client`,
  `requests.Session` and `urllib3.PoolManager`.
- [Timeouts and deadlines](../guide/timeouts.md) — what `total` really promises,
  and how it differs between async and sync runtimes.
- [Retries](../guide/retries.md) — the full decision ladder behind that `503` save.
