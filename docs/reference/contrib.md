---
copy_page: false
---

# Contrib

## Deadline budgets

::: clientwright.contrib.deadline

## Settings

::: clientwright.contrib.settings

## Dishka

`clientwright.contrib.dishka` imports `dishka` at module import time (by design —
a DI integration without the DI library is meaningless), so it is documented
here rather than auto-rendered.

```python
from clientwright.contrib.dishka import ClientwrightProvider
```

**`ClientwrightProvider(adapter, config, deps=None, *, component=None, client_type=None)`**
— a `dishka.Provider` with `scope=Scope.APP` providing:

- `ClientRuntime` — the injected `deps.runtime` if given, handed back as it
  came; else `ClientRuntime.for_config(config)` with the
  `http_client_circuit_state` listener wired the way an adapter wires it. One
  per container (per component), shared.
- `ClientHandle[Any]` — an async generator provide that builds the native client
  with the shared runtime and closes it (`aclose()` / `close()`) in `finally`
  when the container shuts down.
- the native client under `client_type`, when given — `handle.client`, the
  same object, so `httpx.AsyncClient` resolves to what the handle holds.

`component` puts all three in a Dishka component: one provider per upstream in
one container, resolved with `container.get(..., component="github-api")` or
injected as `Annotated[..., FromComponent("github-api")]`.

Usage, scope rules and several upstreams in one container:
[Guide → Dependency injection](../guide/dishka.md).
