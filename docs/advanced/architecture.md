# Architecture

This page is for reading the source, debugging a weird case, or deciding whether
to trust the library with something unusual. Nothing here is required to *use*
clientwright.

## The layout

```text
clientwright/
├── core/          # zero-dependency: stdlib only, enforced by import-linter
│   ├── config.py         # ClientConfig and friends; UNSET sentinel
│   ├── model.py          # FailureKind, Outcome, Attempt, RequestInfo
│   ├── plan.py           # compile_plan, ClientRuntime, ClientHandle
│   ├── capabilities.py   # the honesty machinery
│   ├── engine/           # the two attempt loops + redirect logic
│   ├── policy/           # retry, circuit, budget, timeout, concurrency - pure
│   ├── telemetry/        # emitter, frozen names, redaction, null backends
│   ├── contracts/        # the protocols adapters and backends implement
│   └── testing/          # OriginServer, RecordingMetrics, ManualClock
├── adapters/      # one package per SDK; extras-gated, mutually independent
└── contrib/       # deadline-budget and dishka glue
```

Three import-linter contracts hold the shape: the core never imports adapters,
the core imports nothing outside the stdlib, and adapters never import each
other. (The httpx and httpx2 adapters share a private `_httpx_shared` module that
is deliberately outside the independence contract — it is the *family's* core,
SDK-agnostic by construction.)

## One call through the machine

Every logical call, on every adapter, walks the same fixed order:

```text
deadline computed (config total ∩ ambient budget)
→ static + provider headers injected (caller's win)
→ per-origin slot acquired          (if per-host limits are emulated)
→ circuit.check                     (outside the retry loop - one admission)
→ hop loop:
    attempt loop:
        per-attempt timeouts planned from the remaining budget
        deadline header stamped
        send  ── the ONLY thing the adapter does
        outcome classified (response status or exception → FailureKind)
        retry decision (pure function) → maybe sleep, rewind body, go again
    redirect planned? → drain response, retarget request, next hop
→ circuit.record                    (ONE final signal - or record_aborted on cancellation)
→ telemetry closed in finally       (metrics, span, inflight — every path)
```

The interesting properties fall out of the order, not out of cleverness:

- The breaker cannot be pumped by retries (`check`/`record` bracket the whole
  call).
- Cancellation is a first-class third outcome: a call that died without a
  classified result *aborts* the breaker — neither success nor failure — and
  still closes its telemetry.
- Backoff can never sleep through the deadline, because the decision function
  receives the remaining budget and refuses.

## Views and normalizers: the adapter contract

The engine never touches an SDK object. It sees three small protocols:

- **`RequestView`** — method, URL, mutable headers, caller timeouts,
  `apply_timeouts`, `retarget` (for redirect hops).
- **`ResponseView`** — status, header access, `location`.
- **Normalizer** (async and sync flavors) — wraps native objects into views,
  classifies the SDK's exceptions into `FailureKind`, and owns the three body
  operations that genuinely differ per SDK: `freeze` (make the body
  replayable), `rewind` (before a retry), `discard` (drain a response so its
  connection returns to the pool).

That is the entire adapter surface. An adapter is a seam installation plus these
translations — the engine, policies and telemetry are inherited, not
reimplemented. It is also why the cross-adapter parity battery is even possible:
the batteries drive the *same engine* through five different translators and
assert the observable behavior is identical.

## Compiled plans and the runtime split

`build()` does the thinking once, not per request:

- **`CallPlan`** (frozen) — the compiled config: timeout planner, retry policy,
  capability report, feature flags. Immutable, shared, cheap to read on the hot
  path.
- **`ClientRuntime`** (long-lived, thread-safe) — the state: circuit registries,
  retry-budget buckets, per-origin semaphores, the clock and the RNG. This is
  the object that must be application-scoped; the whole
  [DI story](../guide/dishka.md) is about keeping it alive.

The handle glues client + plan + runtime + report together and rides on the
client instance itself (a weak registry catches exotic objects), which is how
`inspect(client)` works without a global lookup table.

## Where each seam lives

| Adapter | Seam | Why there |
|---|---|---|
| httpx / httpx2 | custom transport | the documented extension point below the client API; nothing can bypass it |
| aiohttp | client middleware + TraceConfig | middleware is the request path; the trace side-channel observes what middleware cannot (connection reuse, a request sent with `middlewares=()`) |
| requests | mounted `HTTPAdapter` | the blessed extension point; also where the per-attempt timeout is injected |
| urllib3 | per-instance `urlopen` wrap | no lower hook exists; per-instance keeps `type(...)` exact and other managers untouched |

Each seam's honest limitations are on its [adapter page](../adapters/index.md);
the declarations live in code as `AdapterCapabilities`.
