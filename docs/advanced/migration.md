# Migration

Three starting points, three sizes of job. In every case the end state is the
same: call sites keep speaking their SDK's language, and resilience moves into
the build step.

## From a bare SDK client

The smallest migration there is — swap the constructor for `build`:

```diff
- client = httpx.AsyncClient(base_url="https://api.example.com", timeout=10.0)
+ config = ClientConfig(
+     service_name="orders",
+     base_url="https://api.example.com",
+     timeout=TimeoutConfig(total=10.0),
+ )
+ client = build("httpx", config)
```

Call sites do not change: it is still an `httpx.AsyncClient`. What changes is
what you can delete — hand-rolled retry decorators, `tenacity` wrappers around
individual calls, ad-hoc metrics middleware. Do delete them: a second retry loop
above the engine multiplies attempts (their 3 × our 3 = 9 hits on a struggling
upstream) and corrupts the accounting. If you *want* application-level retries
around a whole operation, set `retry=None` in the config and keep exactly one
loop.

Watch the first `handle.report` (or run with `on_unsupported="strict"`) — knobs
your old constructor set that the adapter cannot express will announce
themselves.

## From a wrapper-style client kit

If you are coming from an in-house wrapper (the `ResilientClient`-shaped
pattern), the mechanical steps:

1. **Unwrap the call sites.** The wrapper's `await wrapper.get(...)` becomes the
   native `await client.get(...)` — usually a rename, since most wrappers
   mirrored the SDK's verbs anyway.
2. **Move construction into DI.** One `ClientConfig` per upstream, built at APP
   scope; the [dishka provider](../guide/dishka.md) replaces whatever factory
   the wrapper had. This is where breaker state stops dying per request — for
   many wrapper kits, that alone is the biggest behavioral fix of the
   migration.
3. **Keep exception handlers.** Engine errors dual-inherit the native family, so
   `except httpx.HTTPError` / `except requests.RequestException` blocks survive.
   Handlers that caught wrapper-specific exception types map onto
   `CircuitOpenError`, `DeadlineExceededError`, `TooManyRedirectsError`.
4. **Re-point per-call metadata.** Route templates and idempotency flags move to
   the [per-call channel](../guide/per-call-options.md).

## Dashboards: the metric rename

clientwright's schema is `http_client_*` with mandatory `adapter` and `seam`
labels — a deliberate break from ad-hoc `rest_client_*`-style names, because the
label contract changed too (per-attempt vs per-call counting, `outcome`
taxonomy, `route` templates). Principles for the translation:

| You were graphing | Now graph |
|---|---|
| request counter | `http_client_requests_total` — one per *logical call* (retries no longer inflate it) |
| request duration | `http_client_request_duration_seconds` — whole call, all attempts |
| retry counter | `http_client_attempts_total` minus `requests_total`, or the ratio of the two |
| error counter | `requests_total{outcome!="success"}`, split by the `outcome` taxonomy |
| breaker state | `http_client_circuit_state` (0 / 1 / 2 = closed / half-open / open) |

Migrate dashboards before flipping services, run both graphs side by side during
the rollout, and expect the *shapes* to differ where the old kit counted
attempts as requests. If a hard cutover is impossible, a parallel compat emitter
with legacy names is an additive extension point — ask for it rather than
forking the schema.

## Behavior differences worth expecting

An honest list of "the graph moved" moments after migrating from typical
wrapper kits:

- **Fewer retries than before.** Non-idempotent POSTs stop being retried unless
  a call site vouches; the retry budget caps sustained retry traffic at ~10 %.
  Both are features wearing the costume of a regression.
- **Faster failures during outages.** The breaker rejects locally once an origin
  is declared down; latency graphs improve while error graphs spike — that is
  the trade working.
- **`total_timeout` appears.** Calls that used to run 40 s across attempts now
  die at your configured total with a clean outcome label.
- **One call, one count.** Redirect hops and retries stop inflating request
  counters; absolute call numbers may drop with zero traffic change.
