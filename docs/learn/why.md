# Why clientwright

This page is the reasoning behind the library. If you just want to make requests,
skip to [Your first client](first-client.md).

## The wrapper trap

The standard way to add retries and metrics to an HTTP client is to wrap it:

```python
class ResilientClient:  # the pattern clientwright exists to kill
    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def get(self, url):
        for attempt in range(3):
            ...
```

Wrappers have a short honeymoon. Then reality arrives:

- Someone needs `client.stream(...)`, which the wrapper never exposed, so they grab
  `wrapper._client` — and that call has no retries, no metrics, no breaker. Nothing
  fails loudly. The dashboard just quietly stops telling the truth.
- A third-party SDK wants "an `httpx.AsyncClient`", and your wrapper isn't one.
- The wrapper grows a second implementation for aiohttp, a third for requests.
  Three retry loops, three ideas of what a timeout means, three metric schemas.

clientwright inverts the pattern. Instead of putting resilience *above* the client,
it installs one engine *under* the client's public API, at each library's natural
seam — the httpx transport, the aiohttp client middleware, the requests
`HTTPAdapter`, the urllib3 `urlopen`. What you hold in your hand is the genuine
native client. There is no unwrapped object to escape to, because the escape hatch
*is* the instrumented path.

## One engine

Retry semantics are hard to get right once and miserable to get right five times.
The engine in clientwright's core owns, for every adapter, in this fixed order:

```text
deadline → header injection → per-origin slot → circuit check
   → [redirect-hop loop → attempt loop] → circuit record → telemetry
```

Adapters do not retry, do not follow redirects, do not measure time. They translate
their library's request/response objects into neutral views, classify their
library's exceptions into a shared failure taxonomy, and send. That is the whole
adapter contract — roughly a hundred lines per library.

The consequence: when we fix a retry edge case (say, honoring `Retry-After` only up
to a cap, or refusing to retry a request whose body cannot be replayed), every
adapter gets the fix simultaneously, and a service can swap aiohttp for httpx
without its failure behavior changing.

## Honesty over pretense

The uncomfortable truth about "one API over N libraries" is that the libraries are
genuinely different. requests cannot do HTTP/2. urllib3 has no async. aiohttp
cannot express a per-attempt write timeout. A portability layer that hides those
differences is lying to you.

clientwright's answer is a capability model instead of a pretense. Every adapter
ships a machine-readable declaration of what it supports natively, what the engine
emulates, and what is simply absent. When you build a client, your config is checked
against that declaration and you get a report:

```python
handle = clientwright.build_handle("requests", config)
print(handle.report.dropped)  # e.g. {Capability.HTTP2: "requests is HTTP/1.1 only"}
print(handle.report.emulated)  # what the engine provides on top of the library
```

Set `on_unsupported="strict"` in production configs and an inexpressible knob fails
the build at startup — the honest alternative to config that silently does nothing.

## What clientwright is not

- **Not a new HTTP client.** It has no request API of its own. You keep writing
  `httpx` code, `aiohttp` code, `requests` code.
- **Not a mocking or caching layer.** It composes with those, since the client is
  the real thing (`respx`, `hishel` and friends see a normal httpx client).
- **Not magic.** Everything it applies is visible through
  [`inspect()`](../guide/capabilities.md) and the
  [metric schema](../guide/observability.md).
