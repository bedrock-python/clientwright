# Observability

The observability schema is a **frozen contract**, not a byproduct. Metric names,
label sets and outcome values are constants in one module
(`clientwright.core.telemetry.names`); changing any of them is a breaking release.
That is what makes dashboards portable: every service, every adapter, every SDK —
one set of graphs.

## Wiring it up

Telemetry backends arrive through `AdapterDeps`. Anything you leave out becomes a
null object — the engine never branches on "is metrics configured".

```python
from clientwright import AdapterDeps, ClientConfig, build
from clientwright.adapters.observability import OpenTelemetryTracer, PrometheusClientMetrics

deps = AdapterDeps(
    metrics=PrometheusClientMetrics(),  # clientwright[metrics]
    tracer=OpenTelemetryTracer(),  # clientwright[tracing]
    header_providers=(lambda: {"X-Request-ID": current_request_id()},),
)
client = build("httpx", ClientConfig(service_name="orders"), deps)
```

Both backends are optional protocols — `ClientMetricsProtocol` and
`TracerProtocol` are structural, so plugging in a custom sink means implementing
methods, not inheriting classes. The test double `RecordingMetrics` (see
[Testing](testing.md)) is exactly such an implementation.

## The metric families

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `http_client_requests_total` | counter | service, adapter, seam, method, origin, route, status, outcome | one per **logical call** |
| `http_client_request_duration_seconds` | histogram | service, adapter, seam, method, origin, route | whole-call latency |
| `http_client_body_duration_seconds` | histogram | same | time spent reading the response body |
| `http_client_attempts_total` | counter | service, adapter, seam, method, origin, outcome | one per **physical attempt** |
| `http_client_attempt_duration_seconds` | histogram | same | per-attempt latency |
| `http_client_inflight` | gauge | service, adapter, seam, origin | calls currently in flight |
| `http_client_circuit_state` | gauge | service, adapter, key | 0 closed / 1 half-open / 2 open |
| `http_client_redirect_hops_total` | counter | service, adapter, seam | hops the engine followed |
| `http_client_retry_skipped_total` | counter | service, adapter, seam, reason | wanted to retry, could not: `method` / `non_replayable` / `deadline` / `budget` |
| `http_client_uninstrumented_calls_total` | counter | service, adapter, seam | calls that bypassed the seam (see the [aiohttp page](../adapters/aiohttp.md)) |

Three label conventions to internalize:

- **`outcome`** is `success` or a failure kind (`connect_timeout`, `read_timeout`,
  `total_timeout`, `dns_error`, `disconnected`, `status`, `circuit_open`, ...) —
  one shared taxonomy across every SDK.
- **`status`** is the numeric HTTP status, or the string `none` when no response
  arrived at all. A `503`-then-retry-then-`200` call ends as
  `status="200", outcome="success"`; the `503` lives in `attempts_total`.
- **`route`** comes from the [per-call channel](per-call-options.md) and is
  `unknown` until you set it.

The ratio everyone ends up graphing:
`attempts_total / requests_total` is your retry amplification per origin — the
number that tells you an upstream is degrading *before* the breaker opens.

## Traces

With a tracer wired, every logical call is one `CLIENT` span — `HTTP GET` — with
`http.request.method`, `server.origin`, a redacted `url.full`, the response status
and an error status on failure. The engine injects `traceparent` (and whatever
your propagator emits) into outgoing headers **from the client span itself**, so
the upstream's server span becomes its child, not its sibling. Attempts and
redirect hops stay inside the one span: your trace waterfall shows the call as
your caller experienced it.

## Logs

The built-in logging channel writes structured records to the standard `logging`
module under `clientwright.client.<service_name>` — call started (DEBUG), call
finished (INFO, configurable via `success_log_level`), call failed (WARNING) —
with method, redacted URL, outcome, status, duration, attempts and hops in
`extra`. Route it with your normal logging config; there is nothing bespoke to
integrate.

## Redaction

URLs in logs and spans pass through a redactor before leaving the process.
Values of sensitive query parameters (`token`, `code`, `client_secret`,
`api_key`, ... ) become `[redacted]`; header capture honors a matching sensitive
set (`Authorization`, `Cookie`, `X-API-Key`, ...). Both sets are extendable:

```python
from clientwright import ClientConfig, ObservabilityConfig

config = ClientConfig(
    service_name="identity",
    observability=ObservabilityConfig(
        sensitive_query_params=frozenset({"token", "sso_ticket"}),
    ),
)
```

## Turning channels off

```python
ObservabilityConfig(logging=False, metrics=True, tracing=False)
```

Each channel is independent. Off means the null backend — zero overhead beyond a
method call, and no `None`-checks anywhere in your code or ours.
