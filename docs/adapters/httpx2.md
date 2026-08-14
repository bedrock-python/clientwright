# httpx2

[httpx2](https://github.com/pydantic/httpx2) is httpx's successor, maintained by
Pydantic Services Inc. — same design, new major line, where the ecosystem's
security and feature work now lands. clientwright treats it as a first-class
member of the httpx *family*: the two adapters share their implementation core,
and their public surfaces are **identical by construction** (a conformance test
compares the exported names of both packages, module by module).

## Migration is one extra and one import path

```diff
- pip install clientwright[httpx]
+ pip install clientwright[httpx2]
```

```python
import httpx2
from clientwright import ClientConfig, build

client = build("httpx2", ClientConfig(service_name="orders"))
assert type(client) is httpx2.AsyncClient
```

Per-call options, error classes, capability record — everything carries the same
names under the new package:

```python
from clientwright.adapters.httpx2 import (
    IDEMPOTENT_EXTENSION,
    ROUTE_EXTENSION,
    HttpxCircuitOpenError,  # deliberately the same class NAME as in adapters.httpx
)
```

The class names are intentionally identical (`HttpxAdapter`,
`HttpxCircuitOpenError`, ...): a migration is a search-and-replace of the import
path, not a vocabulary lesson. The classes themselves inherit `httpx2`'s error
family, so `except httpx2.HTTPError` works exactly as its predecessor did.

## What differs from the httpx page

Operationally, nothing — [everything on the httpx page](httpx.md) applies, with
`httpx` read as `httpx2`. The `adapter` label in metrics reads `httpx2`, which is
the only way your dashboards will notice the migration happened.

Capability records of the two adapters are asserted equal (modulo the adapter
name) in clientwright's own test suite; if a future httpx2 release grows a
capability httpx lacks, that will surface here as a documented divergence, not a
silent one.
