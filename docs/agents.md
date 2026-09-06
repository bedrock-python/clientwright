# clientwright for AI agents

> One page holding everything a coding assistant needs to configure and drive
> clientwright correctly, plus a map of where the rest of the documentation keeps the
> details it leaves out. Give an agent this page rather than the whole site.

| | |
|---|---|
| Package | `clientwright` on PyPI, import root `clientwright` |
| Requires | Python 3.12+. The core has zero dependencies; every adapter needs its own SDK |
| Install | `pip install "clientwright[httpx]"` · extras: `httpx`, `httpx2`, `aiohttp`, `requests`, `urllib3`, `metrics`, `tracing`, `observability`, `deadline`, `dishka`, `all` |
| Async | `build("httpx" \| "httpx2" \| "aiohttp", config)` — returns the SDK's own async client |
| Sync | `build_sync("httpx" \| "httpx2" \| "requests" \| "urllib3", config)` — returns the SDK's own sync client |
| Source | <https://github.com/bedrock-python/clientwright> |

## How to read this page

Every page of this site is also served as raw Markdown at its own URL with `.md` in
place of the trailing slash — this page is `/agents.md`, the retry guide is
`/guide/retries.md` — so anything the map below points at can be fetched as plain text
rather than scraped out of HTML. The **Copy page** control at the top of a page does the
same thing for a human with a chat window open. The exception is the API reference:
`reference/core.md`, `reference/contrib.md` and `reference/testing.md` are mostly
instructions to a docstring renderer, so their Markdown twin is not the API — read them
as HTML, or read the docstrings in the source.

Top to bottom before writing code. [Rules that hold or break the code](#rules-that-hold-or-break-the-code)
is the section correctness lives in — those are the things the library will not save you
from. Every name used below is in the public API; if you need something not listed here,
fetch the page the [documentation map](#documentation-map) points at rather than guessing
a method that sounds plausible.

## Scope

**It does** build the real native client of an HTTP library with one resilience and
observability engine already installed *under* its public API: a wall-clock deadline over
the whole logical call, retries with jittered backoff and a per-origin budget, a circuit
breaker, engine-owned redirects, header injection, and one frozen `http_client_*`
telemetry schema. `build("httpx", config)` returns a genuine `httpx.AsyncClient` —
`type(client) is httpx.AsyncClient` — and the same `ClientConfig` builds an
`aiohttp.ClientSession`, a `requests.Session`, a `urllib3.PoolManager` or an
`httpx2.AsyncClient` with the same semantics.

**It does not** define a request API of its own: you keep calling `client.get(...)` in
your SDK's own vocabulary, and clientwright never wraps, subclasses or proxies the client.
It does not parse configuration files, read environment variables, or ship a settings
model. It does not pool, cache or deduplicate responses, does not do client-side load
balancing (`TargetResolverProtocol` in `core.balancer` is an unimplemented seam), and does
not hide the differences between SDKs — it *declares* them and reports what it could not
apply.

## Mental model

Six nouns and one fixed order.

* **`ClientConfig`** — the whole client described once, transport-free: no `httpx.Timeout`,
  no `aiohttp.ClientTimeout`, no SDK type anywhere. Frozen dataclasses, validated in
  `__post_init__`.
* **Adapter** — one SDK, addressed by a string name (`"httpx"`, `"httpx2"`, `"aiohttp"`,
  `"requests"`, `"urllib3"`). It finds the seam under the SDK's public API, translates
  request and response objects into neutral views, classifies the SDK's exceptions into
  `FailureKind`, and sends. It does not retry, does not follow redirects, does not measure
  time and never writes a metric.
* **Engine** — `AsyncAttemptEngine` / `SyncAttemptEngine` in `core.engine`. One per built
  client, and the only place a retry loop, a deadline, a redirect hop or a telemetry call
  exists. Fixing a retry edge case fixes it for every adapter at once.
* **`AdapterCapabilities`** — what an adapter admits about itself: its seam, whether the
  seam sees a hop or the logical call, whether the call duration ends at headers or at the
  full body, a `Capability -> Support` map (`native` / `emulated` / `degraded` / `absent`),
  the `FailureKind`s it can actually emit, and which finer kinds collapse into coarser ones.
  Importable with no extras installed.
* **`ConfigApplicationReport`** — what happened when this config met this adapter:
  `applied_natively`, `emulated`, `dropped` (`{Capability: reason}`) and
  `dead_retryable_kinds`. `config.on_unsupported` decides whether issues raise, warn or
  stay silent.
* **`ClientRuntime`** — the state that must outlive a client: circuit breakers, retry
  budgets, per-origin limiters. **Application scope.** A fresh runtime per request makes
  the breaker decorative.

`build()` returns the client; `build_handle()` returns a `ClientHandle` holding the client,
the capability record, the report, the runtime, the compiled plan and the right closer.
`inspect(client)` finds that handle again from any client clientwright built.

The order inside one logical call is baked in and not configurable:

```text
deadline (config total ∩ ambient budget)
  -> header injection (config.headers, header_providers, trace context)
  -> per-origin slot (only where the per-host limit is emulated)
  -> circuit check  (once, before any attempt)
  -> body freeze    (when retries or owned redirects are on)
  -> [ redirect-hop loop -> attempt loop ]
  -> circuit record (once, with the FINAL outcome)
  -> telemetry end  (in a finally, on every path)
```

The attempt loop lives *inside* the hop loop: `max_attempts` is per hop, and the total
deadline is the only thing bounding the pair.

## Wiring

```python
import httpx

from clientwright import (
    CircuitBreakerConfig,
    ClientConfig,
    RetryConfig,
    TimeoutConfig,
    build,
    inspect,
)

config = ClientConfig(
    service_name="orders",  # required: the `service` label on every metric and log line
    base_url="https://api.warehouse.example.com",
    timeout=TimeoutConfig(total=10.0, connect=2.0),
    retry=RetryConfig(max_attempts=3),  # the default; spelled out to be visible
    circuit_breaker=CircuitBreakerConfig(fail_threshold=5),
    on_unsupported="strict",  # fail the build on anything the adapter cannot express
)

client: httpx.AsyncClient = build("httpx", config)
assert type(client) is httpx.AsyncClient  # not a subclass, not a wrapper

response = await client.get("/stock/widgets")

handle = inspect(client)
print(handle.report.dropped, handle.report.dead_retryable_kinds)
await client.aclose()
```

The sync twin is the same text with `build_sync`, `httpx.Client` and no `await`. Wiring
telemetry, ambient deadlines and a shared runtime goes through `AdapterDeps`:

```python
from clientwright import AdapterDeps, ClientRuntime, build
from clientwright.adapters.observability import OpenTelemetryTracer, PrometheusClientMetrics

runtime = ClientRuntime.for_config(config)  # APP scope: build it ONCE

deps = AdapterDeps(
    metrics=PrometheusClientMetrics(),  # clientwright[metrics]
    tracer=OpenTelemetryTracer(),  # clientwright[tracing]
    header_providers=(lambda: {"X-Request-ID": "..."},),
    runtime=runtime,
)
client = build("httpx", config, deps)
```

## The API

Everything in this section is exported from `clientwright` unless the table says otherwise.

### Builders and the handle

| Name | Signature | Returns |
|---|---|---|
| `build` | `build(adapter, config, deps=None)` | the SDK's own **async** client, typed `Any` |
| `build_sync` | `build_sync(adapter, config, deps=None)` | the SDK's own **sync** client, typed `Any` |
| `build_handle` | same arguments | `ClientHandle[Any]` (async) |
| `build_sync_handle` | same arguments | `ClientHandle[Any]` (sync) |
| `inspect` / `inspect_client` | `inspect(client)` | `ClientHandle[Any] \| None` — `None` for a foreign object |
| `registered_adapters` | `registered_adapters()` | `('aiohttp', 'httpx', 'httpx2', 'requests', 'urllib3')` |
| `resolve_adapter` | `resolve_adapter(name)` | the adapter class; `UnknownAdapterError` if unknown |
| `register_adapter` | `register_adapter(name, "module.path:Class", "module.path:CAPABILITIES")` | `None` |
| `capabilities_matrix` | `capabilities_matrix()` | `dict[str, AdapterCapabilities]`, extras-free |
| `client_config_from_settings` | `client_config_from_settings(settings, service_name)` | `ClientConfig` |
| `is_set` | `is_set(value)` | `False` only for `UNSET` |

`build` and its siblings are typed `Any` on purpose: the core cannot name
`httpx.AsyncClient` without depending on httpx, so a narrower type would force a cast on
every caller. `client: httpx.AsyncClient = build(...)` type-checks.

`ClientHandle` fields: `client`, `adapter`, `capabilities`, `report`, `runtime`, `plan`,
`aclose` (async builds) and `close` (sync builds). Closing is yours — nothing closes the
client for you except `ClientwrightProvider`.

`AdapterDeps` fields, every one optional: `metrics` (`ClientMetricsProtocol`), `tracer`
(`TracerProtocol`), `header_providers` (`tuple[HeaderProvider, ...]`), `deadline_source`
(`DeadlineSource`), `runtime` (`ClientRuntime`), `clock` (`() -> float`, monotonic).

`ClientRuntime.for_config(config, *, clock=None, rng=None, circuit_listener=None)` builds
the circuit registry, the retry budget registry and the per-origin limiters from a config.
`ClientRuntime(...)` takes the same pieces directly.

### `ClientConfig`

| Field | Default | Meaning |
|---|---|---|
| `service_name` | **required** | non-empty; the `service` label and the logger name |
| `base_url` | `None` | must start with `http://` or `https://`; rejected by the requests and urllib3 adapters |
| `timeout` | `TimeoutConfig()` | see below |
| `pool` | `PoolConfig()` | see below |
| `retry` | `RetryConfig()` | `None` disables retries entirely |
| `circuit_breaker` | `CircuitBreakerConfig()` | `None` disables the breaker |
| `tls` | `TlsConfig()` | |
| `proxy` | `None` | `ProxyConfig(url=...)` or `ProxyConfig(from_env=True)` |
| `headers` | `{}` | injected with setdefault semantics: a caller-set header always wins |
| `redirects` | `RedirectMode.OWNED` | `NATIVE` hands following back to the SDK |
| `max_redirects` | `5` | `>= 0`; the engine raises `TooManyRedirectsError` past it |
| `caller_override` | `CallerOverride.CALLER_WINS` | what a per-call `timeout=` does |
| `deadline_header` | `None` | e.g. `"X-Deadline-Ms"`; stamped with the *remaining* budget in whole ms before each attempt |
| `observability` | `ObservabilityConfig()` | |
| `native` | `NativeOptions()` | raw passthrough, validated at build |
| `on_unsupported` | `UnsupportedPolicy.WARN` | `STRICT` raises `UnsupportedCapabilityError` at build |

### `TimeoutConfig`

| Field | Default | Meaning |
|---|---|---|
| `total` | `30.0` | wall clock for the whole logical call: every attempt, backoff sleep and redirect hop. `None` = unbounded |
| `attempt` | `UNSET` | ceiling for one attempt. Async enforces it by cancellation; sync cannot and reports it dropped |
| `connect` | `5.0` | |
| `read` | `UNSET` | |
| `write` | `UNSET` | |
| `pool_acquire` | `UNSET` | |

`UNSET` is not `None`. `UNSET` means "defer to the adapter's native default" and the
deferral is visible in the report; `None` means "explicitly unbounded". Every value must be
positive. Whatever a phase resolves to, the engine clamps it to the remaining total before
each attempt — a phase that is `None` after resolution becomes exactly the remaining budget.

### `PoolConfig`

| Field | Default |
|---|---|
| `max_connections` | `100` |
| `max_keepalive` | `20` (ignored by aiohttp, which has no such cap) |
| `keepalive_expiry` | `30.0` seconds; `None` forces connections closed on aiohttp |
| `max_connections_per_host` | `UNSET` — setting it also makes the requests and urllib3 pools *blocking* |
| `http2` | `UNSET`; only the httpx family can honour it |

### `RetryConfig`

| Field | Default | Meaning |
|---|---|---|
| `max_attempts` | `3` | total attempts including the first, **per redirect hop**; `>= 1` |
| `initial_backoff` | `0.1` | seconds |
| `max_backoff` | `10.0` | |
| `multiplier` | `2.0` | `>= 1` |
| `jitter` | `0.2` | within `[0, 1]`; multiplicative ±20 % |
| `retryable_kinds` | `DEFAULT_RETRYABLE_KINDS` | `connect_timeout`, `connect_error`, `dns_error`, `pool_timeout`, `read_timeout`, `disconnected` |
| `retryable_status` | `DEFAULT_RETRYABLE_STATUS` | `{429, 502, 503, 504}` — note `500` is absent |
| `methods` | `IDEMPOTENT_METHODS` | `{GET, HEAD, PUT, DELETE, OPTIONS, TRACE}` |
| `respect_retry_after` | `True` | a `Retry-After` (seconds or HTTP-date) replaces the computed backoff |
| `retry_after_max` | `60.0` | cap on what a server may ask for |
| `budget_ratio` | `0.1` | per-origin token bucket: ~10 % of traffic may be retries. `None` disables the budget |
| `require_replayable_body` | `True` | |
| `mode` | `RetryMode.OWNED` | `DELEGATED` is honoured by the urllib3 adapter only |

The decision ladder, in order, is: a retry-worthy outcome (`status_<code>` or
`kind_<kind>`) → attempts left → idempotency → replayable body → the backoff fits in the
remaining deadline → a token in the origin's budget. Refusals at the last four steps emit
`http_client_retry_skipped_total{reason=method|non_replayable|deadline|budget}`.

### `CircuitBreakerConfig`

| Field | Default | Meaning |
|---|---|---|
| `fail_threshold` | `5` | consecutive tripping calls before `CLOSED -> OPEN` |
| `recovery_timeout` | `60.0` | seconds `OPEN` before the next call becomes a probe |
| `half_open_max_calls` | `1` | concurrent probes, the transitioning call included |
| `max_keys` | `512` | LRU cap; only cold, fully closed circuits are evicted |
| `key` | `CircuitKey.ORIGIN` | or `ORIGIN_ROUTE` (needs a per-call `route`), `ORIGIN_METHOD` |
| `trip_kinds` | `DEFAULT_TRIP_KINDS` | timeouts, connect/DNS/TLS errors, disconnects, protocol errors and `STATUS` |

`STATUS` trips only for `5xx`. A `429` or a `404` never trips the breaker.

### `ObservabilityConfig`, `TlsConfig`, `ProxyConfig`, `NativeOptions`

| Config | Fields |
|---|---|
| `ObservabilityConfig` | `logging=True`, `metrics=True`, `tracing=True`, `success_log_level=logging.INFO`, `sensitive_query_params=DEFAULT_SENSITIVE_QUERY_PARAMS`, `url_masker=None` (any `(str) -> str`; must be callable) |
| `TlsConfig` | `verify=True`, `ca_bundle=None`, `cert=None` (a PEM path, a `(cert, key)` pair, or a `(cert, key, password)` triple where the SDK supports one) |
| `ProxyConfig` | `url=None`, `from_env=False` — mutually exclusive, `ValueError` if both are given |
| `NativeOptions` | `NativeOptions.of(slot={...})`; `slots` is `{slot_name: {kwarg: value}}` |

`DEFAULT_SENSITIVE_HEADERS` is exported but is not a config knob: clientwright never emits
headers into a log line or a span, so there is nothing for it to protect here. It exists for
services that log headers themselves, with
`clientwright.core.telemetry.redaction.redact_headers`.

### Data model and enums

| Name | Values / fields |
|---|---|
| `FailureKind` | `connect_timeout`, `read_timeout`, `write_timeout`, `pool_timeout`, `total_timeout`, `connect_error`, `dns_error`, `tls_error`, `protocol_error`, `disconnected`, `body_error`, `status`, `cancelled`, `circuit_open`, `unknown` |
| `Outcome` | `kind` (`None` means success), `status_code`, `retry_after`, `exception`; `.ok` |
| `RequestInfo` | `method`, `origin`, `url`, `route`, `idempotent`; `.circuit_key(mode)` |
| `ResolvedTimeouts` | `connect`, `read`, `write`, `pool_acquire`, `attempt` |
| `CircuitKey` | `ORIGIN`, `ORIGIN_ROUTE`, `ORIGIN_METHOD` |
| `RedirectMode` | `OWNED`, `NATIVE` |
| `RetryMode` | `OWNED`, `DELEGATED` |
| `CallerOverride` | `CALLER_WINS`, `CONFIG_WINS`, `RAISE` |
| `UnsupportedPolicy` | `IGNORE`, `WARN`, `STRICT` |
| `Support` | `NATIVE`, `EMULATED`, `DEGRADED`, `ABSENT` |
| `Capability` | `timeout_total`, `timeout_attempt`, `timeout_connect`, `timeout_read`, `timeout_write`, `timeout_pool`, `deadline_hard`, `pool_limit_total`, `pool_limit_per_host`, `keepalive`, `pool_metrics`, `conn_metrics`, `redirects_ownable`, `native_retry_disableable`, `per_call_options`, `retrofit`, `exact_native_type`, `balancer`, `http2`, `http3`, `proxy` |
| `SeamGranularity` | `HOP`, `LOGICAL` |
| `DurationBoundary` | `HEADERS`, `FULL` |

Every `StrEnum` field on a config is coerced at construction, so `redirects="native"` works
and `redirects="natvie"` raises `ValueError` instead of silently doing nothing.

`AdapterCapabilities`: `adapter`, `seam`, `granularity`, `boundary`, `support`, `emits`,
`collapses`, `notes`, `.support_of(capability)`.
`ConfigApplicationReport`: `adapter`, `applied_natively`, `emulated`, `dropped`,
`dead_retryable_kinds`, `collapsed_kinds`, `native_overrides`, `.has_issues`, `.issues()`,
`.enforce(policy)`. `native_overrides` is part of the record's shape but no shipped adapter
fills it in — read the accepted passthrough off your own `NativeOptions`, not off the
report.

### Per-call options

Two facts only the call site knows: the low-cardinality `route` template for metrics and
the breaker key, and whether *this* non-idempotent request may be repeated.

```python
from clientwright import call_options  # works for every adapter
from clientwright.adapters.httpx import IDEMPOTENT_EXTENSION, ROUTE_EXTENSION

# httpx and httpx2: request extensions, no ambient state
await client.post(
    f"/users/{user_id}/orders",
    json={"sku": "x"},
    extensions={ROUTE_EXTENSION: "/users/{id}/orders", IDEMPOTENT_EXTENSION: True},
)

# aiohttp, requests, urllib3: a ContextVar block around the call
with call_options(route="/users/{id}/orders", idempotent=True):
    session.post(url, json={"sku": "x"})
```

`clientwright.adapters.aiohttp.call_options`, `...requests.call_options` and
`...urllib3.call_options` are the same object as `clientwright.call_options`. The block is
task-local and thread-local, inherited by tasks started inside it, invisible to siblings.
`current_call_options()` reads it.

### Contrib and testing

| Import | Name | Purpose |
|---|---|---|
| `clientwright.contrib.deadline` | `AmbientDeadlineSource()` | `DeadlineSource` reading whatever `use_budget` installed in this task — the right default for a long-lived client |
| | `BudgetDeadlineSource(budget)` | one fixed budget, for a request-scoped client |
| | `use_budget(budget)` | context manager installing a budget; `use_budget(None)` detaches |
| | `current_budget()` | the installed budget or `None` |
| | `DeadlineBudgetProtocol` | structural: `remaining() -> float`, `expired() -> bool` |
| `clientwright.contrib.dishka` | `ClientwrightProvider(adapter, config, deps=None)` | `Scope.APP` provider giving `ClientRuntime` and a `ClientHandle` closed in `finally` |
| `clientwright.core.testing` | `OriginServer()` | in-process fault-injecting origin on an ephemeral localhost port |
| | `RecordingMetrics()` | a `ClientMetricsProtocol` that remembers every record |
| | `ManualClock(start=0.0)` | monotonic clock advanced by hand |

`OriginServer` routes: `/echo`, `/status/{code}`, `/slow/{seconds}`, `/redirect/{n}`,
`/redirect-loop`, `/flaky/{key}/{fails}`, `/retry-after/{seconds}`, `/disconnect`,
`/hang-body/{seconds}`, `/drop-body`, `/garbage`, `/reset`,
`/flaky-disconnect/{key}/{fails}`. It carries `.url` and `.request_count(prefix)`.

### Telemetry

Metric names and label sets are a frozen wire contract in
`clientwright.core.telemetry.names`; changing one is a breaking release.

| Metric | Type | Emitted |
|---|---|---|
| `http_client_requests_total` | counter | once per **logical call** |
| `http_client_request_duration_seconds` | histogram | once per logical call |
| `http_client_body_duration_seconds` | histogram | when the adapter wraps the body stream (httpx family only) |
| `http_client_attempts_total` | counter | once per **physical attempt** (not under `RetryMode.DELEGATED`) |
| `http_client_attempt_duration_seconds` | histogram | same |
| `http_client_inflight` | gauge | ±1 around each logical call |
| `http_client_circuit_state` | gauge | on a breaker transition, **only when the adapter built the runtime** |
| `http_client_redirect_hops_total` | counter | per followed hop |
| `http_client_retry_skipped_total` | counter | `reason=method\|non_replayable\|deadline\|budget` |
| `http_client_uninstrumented_calls_total` | counter | aiohttp only: a request that bypassed the middleware |

`outcome` is `success` or a `FailureKind` value; `status` is the numeric status or the
string `none`; `route` is `unknown` until a call site sets it. Backends:
`clientwright.adapters.observability.PrometheusClientMetrics(prefix=None, registry=REGISTRY, buckets=...)`
(cached per registry and prefix) and `OpenTelemetryTracer(tracer_provider=None)`.

## Adapters

| Adapter | Flavors | Seam | Native slots | Per-call channel |
|---|---|---|---|---|
| `httpx` | async + sync | `transport` | `client`, `transport` | request `extensions` |
| `httpx2` | async + sync | `transport` | `client`, `transport` | request `extensions` |
| `aiohttp` | async only | client `middleware` | `session`, `connector` | `call_options()` |
| `requests` | sync only | mounted `HTTPAdapter` | `session`, `adapter` | `call_options()` |
| `urllib3` | sync only | instance `urlopen` | `manager` | `call_options()` |

Asking an adapter for a flavor it does not have raises `UnsupportedCapabilityError` at
build time, not at call time.

What each one will not do:

* **httpx / httpx2** — identical public names, one import path apart; the family shares its
  implementation. Per-host pool limits are *emulated* by a per-origin in-flight semaphore
  (it limits requests, not connections). DNS failures collapse into `connect_error`.
  Everything TLS- and pool-related goes into the transport constructor, because
  `Client(transport=...)` silently ignores `verify`, `http2` and `limits`.
* **aiohttp** — the session must be constructed inside a running event loop. Write and pool
  timeouts do not exist and are dropped; `pool.max_keepalive` is ignored; HTTP/2 is dropped.
  `ClientTimeout.total` is deliberately `None` so aiohttp's timer cannot wrap the engine's
  own retry loop. The call duration ends at the headers, so there is no body-duration
  metric. A caller writing `session.get(url, middlewares=())` replaces the chain and
  bypasses the engine entirely — that is counted, not prevented.
* **requests** — no `base_url` (a config that sets one fails the build), no write or pool
  timeout, no `attempt` ceiling, no hard deadline. It closes requests' famous hole: the
  engine sends every attempt with a planned `(connect, read)` pair, so a bare
  `session.get(url)` can no longer hang forever. A three-element `cert` (with a key
  password) is refused.
* **urllib3** — no `base_url`. `type(client) is urllib3.PoolManager` holds because the
  engine is an instance attribute, not a subclass. It is the only adapter where
  `pool_acquire` is real, and then only when `pool.max_connections_per_host` makes the pool
  blocking. It is also the only adapter that honours `RetryMode.DELEGATED`, translating
  `RetryConfig` into `urllib3.util.Retry` — `multiplier` is not translated, because urllib3
  fixes the base at 2. Environment proxies are not read; pass `ProxyConfig(url=...)`.

## Rules that hold or break the code

1. **`ClientRuntime` is application-scoped.** It holds the breakers, the retry budgets and
   the per-origin limiters. Build it once, share it through `AdapterDeps(runtime=...)`
   across request-scoped clients. A runtime per request is a breaker with no memory.
2. **A runtime you build yourself has no circuit-state gauge.** The
   `http_client_circuit_state` listener is wired only when the *adapter* builds the runtime.
   Passing `deps.runtime` — including through `ClientwrightProvider` — keeps the breaker
   working and loses that one gauge.
3. **`UNSET` is not `None`.** `UNSET` defers to the adapter's native default and says so in
   the report; `None` means explicitly unbounded. Both differ from a number.
4. **`retryable_kinds` cannot retry a status.** The policy checks `retryable_status` first,
   and the kind branch explicitly skips `FailureKind.STATUS`. Putting `STATUS` in
   `retryable_kinds` does nothing; change `retryable_status` instead.
5. **A `429` is retried but is not a failure.** Only `5xx` becomes
   `FailureKind.STATUS`, so a `429` that survives every retry is recorded as
   `outcome="success", status="429"` and never trips the breaker. A plain `500` is not in
   the default `retryable_status` and is not retried.
6. **`RetryMode.DELEGATED` means "no retries" on every adapter except urllib3.** The engine
   builds no retry policy in that mode, and only the urllib3 adapter translates the config
   into native machinery. On httpx, aiohttp or requests it silently disables retrying and
   per-attempt metrics.
7. **`max_attempts` is per redirect hop.** The attempt loop sits inside the hop loop, so a
   3-attempt policy over a 5-hop chain can issue 15 physical requests — bounded only by the
   total deadline, and still exactly one circuit signal and one `requests_total`.
8. **A body that cannot be replayed vetoes every repeat.** Whenever retries or owned
   redirects are on — both are defaults — the engine freezes the body before the first
   send. The httpx family reads the whole request body into memory; requests replays bytes
   and strings and rewinds a seekable stream; aiohttp and urllib3 replay bytes-backed
   bodies only. Anything else marks the call non-replayable, which forbids every retry and
   every body-preserving redirect. That refusal is a counter
   (`retry_skipped{reason="non_replayable"}`), never an exception — you get the failed
   response, not an error.
9. **The engine will not retry a `POST` on its own.** Pass `idempotent=True` at the call
   site — the extension for httpx, `call_options` elsewhere — and mean it. The reverse is
   *not* symmetric: `idempotent=False` on a `GET` does not stop a retry, because the method
   gate refuses only when the method is outside `retry.methods` **and** the flag is false.
   To stop retrying a method, remove it from `RetryConfig.methods`.
10. **The total deadline covers everything and is only hard on async.** Async engines wrap
    each attempt in a cancellation scope; sync engines cannot cancel a blocked socket, so
    they clamp phases and re-check at attempt boundaries — the failure then arrives as
    `read_timeout`, not `total_timeout`. Sync adapters declare `deadline_hard: absent`.
11. **`caller_override` never lets a caller escape the total.** `CALLER_WINS` replaces the
    config's phases with the caller's, then clamps them to the remaining budget; a
    `timeout=60` on a call with 3 seconds left gets 3 seconds. `RAISE` makes a per-call
    timeout an error.
12. **Do not stack a second retry loop.** `tenacity` or a hand-rolled decorator above the
    client multiplies attempts (3 × 3 = 9 against a struggling upstream) and corrupts the
    accounting. Keep one loop: theirs *or* `retry=None` plus yours.
13. **Native passthrough is validated, not forwarded.** An unknown slot, a key the engine
    owns (`timeout`, `transport`, `retries`, `max_redirects`, pool and TLS knobs), a
    misspelled constructor argument or a collision with a config field you also set is a
    `NativeConfigError` at build time.
14. **`on_unsupported` decides how loud a mismatch is.** `WARN` (the default) logs and
    continues; `STRICT` raises `UnsupportedCapabilityError` at build. Production configs
    should be `STRICT` — a dropped knob becomes a failed deploy instead of a false belief.
15. **`dead_retryable_kinds` is a real class of bug.** A retry trigger the chosen adapter
    can never emit (`dns_error` on the httpx family, which collapses it into
    `connect_error`) is configured, believed in and impossible. The report names them.
16. **You close the client.** `handle.aclose` / `handle.close` exist and nothing calls them
    for you except `ClientwrightProvider`'s generator provide.
17. **`base_url` is httpx-family and aiohttp only.** requests and urllib3 reject it at build
    rather than inventing a wrapper.
18. **The route label is `unknown` until you set it, and must be a template.** An
    interpolated URL as `route` is a cardinality bomb in the metrics and, under
    `CircuitKey.ORIGIN_ROUTE`, in the breaker's key space too.

## Common mistakes

```python
# WRONG - a runtime per client, so the breaker forgets everything each request
from clientwright import AdapterDeps, ClientConfig, ClientRuntime, build


def get_client(config: ClientConfig):
    return build("httpx", config, AdapterDeps(runtime=ClientRuntime.for_config(config)))


# RIGHT - one runtime for the process, shared by every client of that upstream
RUNTIME = ClientRuntime.for_config(config)


def get_client(config: ClientConfig):
    return build("httpx", config, AdapterDeps(runtime=RUNTIME))
```

```python
# WRONG - a wrapper around the client, which is the pattern the library exists to remove
from clientwright import ClientConfig, build


class ResilientClient:
    def __init__(self, config: ClientConfig):
        self._client = build("httpx", config)

    async def get(self, url: str):
        for _ in range(3):  # a second retry loop: 3 x 3 = 9 requests
            return await self._client.get(url)


# RIGHT - the built client already is the resilient client
client = build("httpx", config)
response = await client.get("/stock")
```

```python
# WRONG - retrying a status by putting it in retryable_kinds
from clientwright import FailureKind, RetryConfig

RetryConfig(retryable_kinds=frozenset({FailureKind.STATUS}))  # does nothing at all

# RIGHT - statuses have their own list
RetryConfig(retryable_status=frozenset({429, 500, 502, 503, 504}))
```

```python
# WRONG - expecting the engine to retry a POST because the config allows the status
await client.post("/orders", json=payload)

# RIGHT - the call site vouches for this particular POST
from clientwright.adapters.httpx import IDEMPOTENT_EXTENSION, ROUTE_EXTENSION

await client.post(
    "/orders",
    json=payload,
    extensions={ROUTE_EXTENSION: "/orders", IDEMPOTENT_EXTENSION: True},
)
```

```python
# WRONG - assuming DELEGATED means "the SDK retries for me" on any adapter
from clientwright import ClientConfig, RetryConfig, RetryMode

ClientConfig(service_name="orders", retry=RetryConfig(mode=RetryMode.DELEGATED))  # httpx: no retries

# RIGHT - delegated is a urllib3 carve-out; everywhere else leave the engine in charge
ClientConfig(service_name="orders", retry=RetryConfig(mode=RetryMode.OWNED))
```

```python
# WRONG - smuggling an engine-owned knob through native passthrough
from clientwright import ClientConfig, NativeOptions, TimeoutConfig

ClientConfig(service_name="x", native=NativeOptions.of(client={"timeout": 5.0}))  # ReservedNativeKeyError

# RIGHT - the config owns it; passthrough is for what the config does not cover
ClientConfig(
    service_name="x",
    timeout=TimeoutConfig(total=5.0),
    native=NativeOptions.of(client={"trust_env": False}),
)
```

```python
from clientwright import ClientConfig, UnsupportedPolicy, build_sync, build_sync_handle

# WRONG - trusting that a config written for httpx means the same thing on requests
client = build_sync("requests", ClientConfig(service_name="reports"))

# RIGHT - make the build fail on anything the adapter could not express, and read it
handle = build_sync_handle(
    "requests",
    ClientConfig(service_name="reports", on_unsupported=UnsupportedPolicy.STRICT),
)
assert not handle.report.has_issues
```

## Errors

Everything the library raises on its own authority derives from `ClientwrightError`.
Errors raised on the call path derive from `CallError` and are re-raised by each adapter as
a class that *also* inherits the SDK's own error family, so an existing
`except httpx.HTTPError` or `except aiohttp.ClientError` keeps working.

| Error | Raised when |
|---|---|
| `UnknownAdapterError` | `build("htpx", ...)` — carries `.name` and `.known` |
| `UnsupportedCapabilityError` | `on_unsupported="strict"` with issues in the report; also an adapter asked for a flavor it lacks, `base_url` on requests or urllib3, or a password-protected client cert on requests |
| `NativeConfigError` | base of the passthrough errors: `UnknownNativeSlotError`, `ReservedNativeKeyError`, `UnknownNativeKeyError` (with a did-you-mean), `NativeConfigConflictError` — the four subclasses live in `clientwright.core.errors` |
| `CircuitOpenError` | the circuit for this key is open; `.key`, `.retry_after` |
| `DeadlineExceededError` | the total deadline is exhausted; `.total` |
| `TooManyRedirectsError` | more than `max_redirects` hops; `.hops` |
| `NotReplayableError` | exported, and passed through the adapter translators unchanged, but the engine never raises it: a non-replayable body ends the call with the response it already has plus a `retry_skipped{reason="non_replayable"}` counter |
| `CallerOverrideForbiddenError` | a per-call timeout under `CallerOverride.RAISE`; a `CallError`, importable from `clientwright.core.policy.timeout` |

Per-adapter classes are the same three names with the adapter's prefix:
`HttpxCircuitOpenError`, `HttpxDeadlineExceededError`, `HttpxTooManyRedirectsError` (also
under `clientwright.adapters.httpx2`, deliberately with the same class names), and the
`Aiohttp*`, `Requests*`, `Urllib3*` trios.

## Documentation map

Fetch a page when the task is the one named beside it.

| Page | Read it when |
|---|---|
| [Home](index.md) | a one-screen orientation with the shortest possible example |
| [Why clientwright](learn/why.md) | justifying the library, or arguing against a wrapper |
| [Installation](learn/install.md) | choosing extras and SDK version ranges |
| [Your first client](learn/first-client.md) | writing the very first integration end to end |
| [Sync and async](learn/sync-and-async.md) | picking a flavor, or explaining hard vs soft deadlines |
| [Configuration](guide/configuration.md) | the shape of `ClientConfig`, the defaults, `UNSET` |
| [Timeouts and deadlines](guide/timeouts.md) | total vs phase, caller overrides, deadline propagation |
| [Retries](guide/retries.md) | the decision ladder, backoff, `Retry-After`, the budget |
| [Circuit breaker](guide/circuit-breaker.md) | thresholds, half-open probes, choosing the key |
| [Redirects](guide/redirects.md) | owned vs native, method demotion, cross-origin header stripping |
| [Per-call options](guide/per-call-options.md) | route labels and per-call idempotency |
| [Observability](guide/observability.md) | metric families, labels, spans, log records |
| [Masking PII](guide/masking.md) | scrubbing values a name list cannot reach |
| [Proxies and TLS](guide/proxies-tls.md) | mTLS, private CAs, explicit and environment proxies |
| [Native passthrough](guide/native-options.md) | a knob `ClientConfig` does not cover |
| [Capability honesty](guide/capabilities.md) | reading a report, comparing adapters before a migration |
| [Dependency injection](guide/dishka.md) | wiring the runtime and the client lifecycle in a container |
| [Deadline budgets](guide/deadline-budget.md) | propagating the inbound request's remaining time |
| [Testing your service](guide/testing.md) | `OriginServer`, `RecordingMetrics`, what to mock instead |
| [Choosing an adapter](adapters/index.md) | picking one, or planning a swap |
| [httpx](adapters/httpx.md) | the reference adapter's seam and quirks |
| [httpx2](adapters/httpx2.md) | moving from httpx to its successor |
| [aiohttp](adapters/aiohttp.md) | the middleware seam, the bypass sentinel, the dropped knobs |
| [requests](adapters/requests.md) | the `HTTPAdapter` mount and the closed timeout hole |
| [urllib3](adapters/urllib3.md) | the `urlopen` seam and delegated retries |
| [Architecture](advanced/architecture.md) | reading the source, or debugging a weird case |
| [Writing an adapter](advanced/writing-an-adapter.md) | adding a new SDK behind the same engine |
| [Migration](advanced/migration.md) | moving from a bare SDK or an in-house client kit |
| [API reference](reference/index.md) | what is covered by semver, and where each surface is documented |
| [Core reference](reference/core.md) | an exact signature or docstring — rendered from source, read it as HTML |
| [Adapters reference](reference/adapters.md) | the per-adapter export table, in full |
| [Contrib reference](reference/contrib.md) | the deadline and dishka surfaces |
| [Testing reference](reference/testing.md) | the docstrings of the test instruments |
| [Changelog](changelog.md) | what changed between versions |
