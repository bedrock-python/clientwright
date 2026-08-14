# Redirects

Redirects look trivial until you ask who pays for them. If the SDK follows them
internally, each hop gets its own timeout, retries can multiply across hops, and
your metrics count one call while the wire carried four. clientwright's default is
different: **the engine owns redirects**, and native following stays disabled.

## What "owned" buys you

One logical call has exactly one total deadline, one retry budget, one circuit
signal and one metrics entry — regardless of hop count. Hops are visible as their
own counter instead of inflating call counts:

```text
http_client_requests_total       +1   (the logical call)
http_client_redirect_hops_total  +2   (a 302 chain of two)
```

The engine follows up to `max_redirects` hops (5 by default), then raises
`TooManyRedirectsError` — dual-inherited from the native family, so
`except httpx.TooManyRedirects`-style handlers keep working per adapter.

## The rules of the road

The hop logic mirrors what browsers and mature SDKs converged on:

- `303` — and `301`/`302` after a `POST` — demote the method to `GET` and drop the
  body. `307`/`308` preserve method and body.
- A hop that must *replay* a body (`307` with a `POST`) is only followed if the
  body was replayable; otherwise the redirect response is returned to you as-is
  rather than half-replayed.
- A hop that crosses origins strips `Authorization`, `Proxy-Authorization` and
  `Cookie` — your credentials for service A are not service B's business.
- Relative `Location` headers resolve against the request URL, per RFC.

Each followed hop drains the redirect response first, so its connection returns to
the pool instead of leaking.

## Native mode

If you genuinely want the SDK's own follower (some codebases depend on
SDK-specific redirect hooks), switch it back:

```python
from clientwright import ClientConfig, RedirectMode

config = ClientConfig(service_name="legacy", redirects=RedirectMode.NATIVE)
```

In native mode the engine returns `3xx` responses untouched and the SDK's follower
(with the SDK's semantics and *without* per-hop deadline accounting) takes over.
This is the documented trade, not a bug: pick it only when you need it.
