# Deadline budgets

Your service was given 5 seconds to answer. It has already spent 3. Any outgoing
call it makes now has **2 seconds**, not the 10 written in its config — otherwise
you do work whose result nobody is waiting for, and your caller times out anyway.

That arithmetic is deadline propagation, and `clientwright[deadline]` wires it to
the [`deadline-budget`](https://pypi.org/project/deadline-budget/) library.

## The ambient source

`deadline-budget` deliberately has no implicit context — a `BudgetContext` is
passed from call site to call site by argument. But an HTTP client sits far below
the code that knows the budget, so clientwright's contrib supplies the ambient
channel:

```python
from deadline_budget import BudgetContext

from clientwright import AdapterDeps, ClientConfig, build
from clientwright.contrib.deadline import AmbientDeadlineSource, use_budget

deps = AdapterDeps(deadline_source=AmbientDeadlineSource())
client = build("httpx", ClientConfig(service_name="orders"), deps)

# in the request handler:
with use_budget(BudgetContext.create(total_seconds=5.0)):
    await client.get("/inventory")  # capped by what is LEFT of those 5 seconds
```

Inside the block, the engine intersects the config total with the budget's
remainder and takes the tighter of the two; outside any block the source finds
nothing and the config total applies alone. The client itself stays long-lived
and budget-free — each *call* picks up the budget of the request it happens to
serve.

## Propagation rules

`use_budget` is a `ContextVar` underneath, and the semantics follow from that:

- an `asyncio` task **started inside** the block inherits the budget — a fan-out
  shares its request's deadline;
- sibling tasks and other threads see nothing;
- `use_budget(None)` inside a block **detaches** — for background work spawned by
  a request that must not die with it;
- blocks nest, inner wins, exit restores.

## One fixed budget

For a client scoped to a single request (rare, but it happens), skip the ambient
channel and bind the budget directly:

```python
from clientwright.contrib.deadline import BudgetDeadlineSource

deps = AdapterDeps(deadline_source=BudgetDeadlineSource(budget))
```

## Telling the upstream

Combine with `deadline_header` and the upstream learns the remainder too:

```python
config = ClientConfig(service_name="orders", deadline_header="X-Deadline-Ms")
```

Every attempt stamps the *current* remaining milliseconds — after two attempts
and a backoff sleep, the header says what is genuinely left, and a well-behaved
upstream can decline work it cannot finish in time.

## Structural on purpose

`contrib.deadline` never imports `deadline-budget`. It types the budget
structurally — anything with `remaining() -> float` and `expired() -> bool`
fits — so the extra exists only to pin the real library's version for services
that use it. Your own budget object works identically.
