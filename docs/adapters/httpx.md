# httpx

The reference adapter. httpx is where the seam is cleanest — a documented
`transport` abstraction below the client API — so this adapter has the fewest
compromises and both flavors:

```python
import httpx
from clientwright import ClientConfig, build, build_sync

config = ClientConfig(service_name="orders", base_url="https://wh.example.com")

client = build("httpx", config)  # type(client) is httpx.AsyncClient
sync_client = build_sync("httpx", config)  # type(sync_client) is httpx.Client
```

## Where the engine sits

The adapter installs an engine transport as the client's transport. Everything
that goes through the client — `get`, `stream`, third-party SDKs holding your
client, httpx `auth` flows issuing extra requests — passes through the engine,
because in httpx *everything* goes through the transport. There is no bypass to
guard against, which is why httpx needs no
[uninstrumented-call sentinel](aiohttp.md#the-bypass-sentinel).

Per-scheme proxy routing uses httpx's own `mounts`; explicit and
environment-driven proxies both map onto genuine httpx transports.

## Per-call options

httpx has request extensions, so route and idempotency ride the request:

```python
from clientwright.adapters.httpx import IDEMPOTENT_EXTENSION, ROUTE_EXTENSION

await client.post(
    "/orders",
    json=payload,
    extensions={ROUTE_EXTENSION: "/orders", IDEMPOTENT_EXTENSION: True},
)
```

## Capability notes

- **Total deadline**: hard on async (cancellation), soft on sync — httpx itself
  has *no* wall-clock timeout; this is the engine's addition.
- **Errors**: httpx's exception taxonomy is the richest of the five, so
  `FailureKind` mapping is nearly one-to-one (`ConnectTimeout` →
  `connect_timeout`, `ReadTimeout` → `read_timeout`, ...). DNS failures are not
  natively distinguishable from connect errors and are declared collapsed.
- **Dual-family errors**: engine-raised failures inherit both families —
  `HttpxCircuitOpenError` is a `CircuitOpenError` *and* an `httpx.HTTPError`, so
  existing `except httpx.HTTPError` blocks keep working.
- **HTTP/2**: native (`pool.http2=True`, requires the `h2` extra of httpx
  itself).
- **Composability**: because the client is genuine, the httpx ecosystem applies —
  `respx` mocks it, `auth=` flows run *through* the engine (token-refresh
  requests get retries and metrics too), event hooks fire as usual.

!!! warning "Do not replace the transport"

    `httpx.AsyncClient(transport=...)` semantics still exist on the built client —
    handing it a new transport would remove the engine. The engine transport is
    the one thing on this client you should treat as load-bearing.
