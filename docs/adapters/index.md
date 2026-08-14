# Choosing an adapter

Short version: **new async service → httpx. New sync service → httpx. Existing
codebase → the adapter matching the SDK you already use.** clientwright's job is
to make that second answer safe — you keep your library and gain the engine.

## The lineup

| Adapter | Flavors | Seam | The one-line story |
|---|---|---|---|
| [httpx](httpx.md) | async + sync | transport | the reference adapter; cleanest seam in the ecosystem |
| [httpx2](httpx2.md) | async + sync | transport | httpx's successor under Pydantic stewardship; same adapter surface, one import apart |
| [aiohttp](aiohttp.md) | async | client middleware | highest-throughput async stack; a few sharp edges the adapter files down |
| [requests](requests.md) | sync | `HTTPAdapter` | the lingua franca of sync Python; adapter closes its famous no-default-timeout hole |
| [urllib3](urllib3.md) | sync | `urlopen` | the foundation layer; home of delegated retries |

Every adapter passes the same cross-adapter parity battery in CI: identical retry
counts, breaker behavior, deadline handling, redirect semantics and metric names
on identical scenarios. The differences that remain are *declared* — each page
below leads with its capability quirks, and
[`capabilities_matrix()`](../guide/capabilities.md) gives you the same data as
code.

## Switching adapters

Because the config is transport-free and the metric schema frozen, a migration
between adapters is:

1. change the extra in your dependency file,
2. change the string in `build("aiohttp", ...)`,
3. rewrite the *call sites* from one SDK's API to the other's (clientwright does
   not hide this — you were always writing real SDK code),
4. read `handle.report` under `on_unsupported="strict"` and address what it says.

Dashboards, alerts, retry behavior and breaker tuning carry over untouched.

## The experimental tier

`tornado`, `aiosonic` and `niquests` sit outside the parity guarantee: adapters
may exist or appear on demand, but they do not gate releases. (A note for
`niquests` specifically: its install replaces `urllib3` in `site-packages` via a
`.pth` trick, which is why it will never be part of the `all` extra.)

Third-party adapters register with two import strings and join the same
machinery:

```python
import clientwright

clientwright.register_adapter(
    "myhttp",
    "my_pkg.adapter:MyHttpAdapter",
    "my_pkg.capabilities:CAPABILITIES",
)
```

See [Writing an adapter](../advanced/writing-an-adapter.md).
