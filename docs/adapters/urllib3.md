# urllib3

The foundation layer, for codebases that use it directly. This adapter has the
most unusual seam of the five: there is no transport slot and no middleware
chain, so the engine wraps the `urlopen` method of a genuine
`urllib3.PoolManager` — per **instance**, not per class:

```python
import urllib3
from clientwright import ClientConfig, build_sync

manager = build_sync("urllib3", ClientConfig(service_name="storage"))
assert type(manager) is urllib3.PoolManager  # exactly - not a subclass

response = manager.request("GET", "https://s3.internal.example.com/bucket/key")
```

`type(...) is urllib3.PoolManager` holds because nothing is subclassed: the
engine hook lives on the one instance you built. Other `PoolManager` instances
in the process are untouched.

Like requests, urllib3 has no base-URL concept — call sites use absolute URLs,
and `base_url` in the config is rejected at build.

## Owned retries (the default)

In the default `RetryMode.OWNED`, the engine sends every attempt with
`retries=False, redirect=False` underneath — urllib3's native machinery is
parked and the engine's loop, budget, deadline and metrics apply exactly as on
every other adapter. Native redirect recursion is likewise suppressed from
double-counting via the engine's reentrancy guard.

## Delegated retries (the carve-out)

urllib3 is the one SDK whose native `Retry` object is a real, battle-tested
engine of its own — and some operations teams have a decade of muscle memory
around it. `RetryMode.DELEGATED` hands the loop down instead of parking it:

```python
from clientwright import ClientConfig, RetryConfig, RetryMode

config = ClientConfig(
    service_name="storage",
    retry=RetryConfig(max_attempts=3, mode=RetryMode.DELEGATED),
)
```

Your `RetryConfig` is translated into a `urllib3.util.Retry` (attempts, backoff
factor, status list, redirect cap) and urllib3 runs the attempts *below* the
seam. Two honest consequences, both declared:

- `http_client_attempts_total` is **not emitted** — the engine cannot see
  attempts it does not perform, and fabricating one record per logical call
  would be a lie. Call-level metrics remain complete.
- Per-attempt engine features (attempt ceilings, per-attempt deadline stamping)
  do not apply inside the delegated loop; the total deadline still caps the
  logical call from outside.

`DELEGATED` on any other adapter is refused at build time — no other SDK has a
native engine worth delegating to.

## Per-call options

```python
from clientwright.adapters.urllib3 import call_options

with call_options(route="/bucket/{key}", idempotent=True):
    manager.request("POST", url, body=payload)
```

## Capability notes

- **Deadline: soft** (sync runtime), like requests.
- **Proxies**: an explicit proxy builds a genuine `urllib3.ProxyManager`;
  environment-driven proxies are not expressible on this seam and are declared
  dropped with the reason.
- **Pool-acquire**: expressible only together with a per-host pool limit
  (urllib3's blocking-pool mode); configured alone it is dropped with a hint.
- **HTTP/2: absent.**
- **Errors**: `Urllib3CircuitOpenError` and friends inherit
  `urllib3.exceptions.HTTPError`.
