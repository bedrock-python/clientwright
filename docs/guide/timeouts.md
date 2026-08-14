# Timeouts and deadlines

Most HTTP libraries answer "how long may this take?" with phase timeouts: so many
seconds to connect, so many to read a chunk. None of them answers the question your
SLO actually asks: **when is this call, as a whole, over?** A call that retries
three times with backoff can honor every phase timeout and still take a minute.

clientwright separates the two concepts cleanly.

## The total is a wall clock

```python
from clientwright import UNSET, ClientConfig, TimeoutConfig

config = ClientConfig(
    service_name="orders",
    timeout=TimeoutConfig(
        total=10.0,  # the whole logical call: attempts + backoff + redirects
        connect=2.0,  # one phase of one attempt
        read=UNSET,  # defer to the adapter's native default (this IS the default)
    ),
)
```

`total` starts ticking when the call enters the engine and covers *everything*
inside it: every attempt, every backoff sleep, every redirect hop. It is measured
on a monotonic clock. Before each attempt the engine computes the remaining budget,
clamps every phase timeout to it, and refuses to start an attempt (or a backoff
sleep) that cannot fit.

On async adapters the total is **hard**: the attempt runs inside a cancellation
scope, so a stuck read is cancelled mid-flight and the call raises with the outcome
`total_timeout`. On sync adapters it is **soft** — see
[Sync and async](../learn/sync-and-async.md#the-one-honest-difference-hard-vs-soft-deadlines)
for exactly what that means and why it is declared rather than hidden.

## Phase timeouts

`connect`, `read`, `write` and `pool_acquire` cap phases of a *single attempt* and
translate to whatever the SDK natively understands. Two things are worth knowing:

- Any phase left `UNSET` uses the adapter's own default, and that deferral shows up
  in the build report. clientwright does not invent a fourth opinion about what a
  good read timeout is.
- A phase an adapter cannot express (aiohttp has no per-attempt write timeout,
  requests has no pool-acquire timeout) is reported as dropped — loudly under
  `on_unsupported="strict"`.

`attempt` is the odd one out: a ceiling for one whole attempt regardless of phase.
Async engines enforce it by cancellation; sync engines by clamping phases.

## When the caller also passes a timeout

Native clients accept per-call timeouts (`client.get(url, timeout=...)`,
`session.get(url, timeout=...)`). Now there are two opinions — the config's and the
caller's. `caller_override` decides, explicitly:

```python
from clientwright import CallerOverride

ClientConfig(service_name="x", caller_override=CallerOverride.CALLER_WINS)  # default
```

| Mode | Meaning |
|---|---|
| `CALLER_WINS` | the caller's phases replace the config's — but stay clamped by the remaining total |
| `CONFIG_WINS` | the caller's value is ignored |
| `RAISE` | passing a per-call timeout is an error — for teams that want one source of truth |

Note what even `CALLER_WINS` does **not** allow: escaping the total. A caller
passing `timeout=60` into a call with 3 seconds of budget left gets 3 seconds.

## Propagating the deadline downstream

If your platform passes deadlines between services, two hooks matter:

```python
from clientwright import AdapterDeps, ClientConfig

config = ClientConfig(
    service_name="orders",
    deadline_header="X-Deadline-Ms",  # (1)!
)
deps = AdapterDeps(deadline_source=my_source)  # (2)!
```

1. Before each attempt the engine stamps the *remaining* budget, in whole
   milliseconds, into this header — so the upstream sees what is actually left, not
   your configured total.
2. A `DeadlineSource` contributes an ambient budget (for example, the remainder of
   the inbound request you are currently serving). The engine takes the tightest of
   the config total and the source's value. The ready-made source for
   `deadline-budget` lives in [Deadline budgets](deadline-budget.md).

## What you observe

A call that dies on the total raises `DeadlineExceededError` — dual-inherited from
the adapter's native error family, so your existing `except httpx.TimeoutException`
keeps catching it — and lands in metrics with `outcome="total_timeout"`. A phase
that fired first keeps its own name (`connect_timeout`, `read_timeout`, ...); the
taxonomy never merges them.
