# Contrib

## Deadline budgets

::: clientwright.contrib.deadline

## Dishka

`clientwright.contrib.dishka` imports `dishka` at module import time (by design —
a DI integration without the DI library is meaningless), so it is documented
here rather than auto-rendered.

```python
from clientwright.contrib.dishka import ClientwrightProvider
```

**`ClientwrightProvider(adapter, config, deps=None)`** — a `dishka.Provider`
with `scope=Scope.APP` providing:

- `ClientRuntime` — the injected `deps.runtime` if given, else
  `ClientRuntime.for_config(config)`; one per container, shared.
- `ClientHandle[Any]` — an async generator provide that builds the native client
  with the shared runtime and closes it (`aclose()` / `close()`) in `finally`
  when the container shuts down.

Usage, scope rules and multi-upstream patterns:
[Guide → Dependency injection](../guide/dishka.md).
