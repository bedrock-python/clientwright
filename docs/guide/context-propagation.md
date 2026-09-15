# Context propagation

Your service was handed a request carrying `x-request-id: rid-1`. servicewright's
transports bind that id — and the user, tenant and trace ids next to it — into
its request context for the whole unit of work. Every outgoing call that request
makes should carry the same ids, or the trail stops at your service.

`clientwright[servicewright]` wires that. servicewright's `propagation_metadata`
already satisfies the `HeaderProvider` protocol as it is; the contrib module
names the join so no service writes it by hand.

## Wiring it

```python
from clientwright import AdapterDeps, ClientConfig, build
from clientwright.contrib.servicewright import servicewright_headers

deps = AdapterDeps(header_providers=servicewright_headers())
client = build("httpx", ClientConfig(service_name="orders"), deps)

# inside a unit of work the transport has bound (or your own bind_context block):
await client.get("/inventory")  # x-request-id, x-user-id, x-tenant-id, x-trace-id
```

Only the ids actually bound travel: outside any bound context the provider
returns nothing and the request goes out unchanged. A header the caller set
explicitly is never overwritten — providers fill in what is missing.

## Composing

`servicewright_headers()` returns the providers tuple rather than a whole
`AdapterDeps`, so it sits next to everything else you inject:

```python
from clientwright.adapters.observability import PrometheusClientMetrics
from clientwright.contrib.deadline import AmbientDeadlineSource
from clientwright.contrib.servicewright import servicewright_headers

deps = AdapterDeps(
    metrics=PrometheusClientMetrics(),
    header_providers=servicewright_headers(),
    deadline_source=AmbientDeadlineSource(),
)
```

Your own providers go in the same tuple: `(*servicewright_headers(), my_provider)`.

## A different header mapping

`propagation_metadata` takes a `{context_key: header_name}` mapping; the helper
uses servicewright's standard one. For another, build the tuple yourself:

```python
from functools import partial

from servicewright import propagation_metadata

deps = AdapterDeps(header_providers=(partial(propagation_metadata, {"request_id": "X-Correlation-ID"}),))
```

## Why an extra

Unlike `contrib.deadline`, this module imports servicewright at import time —
the real function is the point, there is nothing structural to type — so a
missing extra fails at `import clientwright.contrib.servicewright` with an
install hint. The extra pins `servicewright>=0.1,<1`; the export has not changed
since 0.1.0.
