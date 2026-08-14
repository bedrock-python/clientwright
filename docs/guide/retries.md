# Retries

The retry loop is the part of an HTTP client everyone writes and almost everyone
gets subtly wrong: retrying non-idempotent requests, hammering a struggling
upstream, replaying bodies that cannot be replayed, sleeping past the deadline.
clientwright's retry policy is one pure function, shared by every adapter, that
walks an explicit decision ladder.

## The config

```python
from clientwright import ClientConfig, RetryConfig

config = ClientConfig(
    service_name="orders",
    retry=RetryConfig(
        max_attempts=3,  # total attempts, including the first
        initial_backoff=0.1,  # seconds; then × multiplier per attempt
        max_backoff=10.0,
        multiplier=2.0,
        jitter=0.2,  # ±20 % noise so clients do not sync up
    ),
)
```

Every field has a working default — `retry=RetryConfig()` and omitting the field
entirely are the same thing. `retry=None` turns the loop off.

## What gets retried

Two lists decide, and both are yours to change:

- **Statuses**: `429`, `502`, `503`, `504` by default. Note what is absent: a plain
  `500` is treated as "the server executed something and failed" — replaying it is
  a decision you must opt into, not a default.
- **Failure kinds**: `connect_timeout`, `connect_error`, `dns_error`,
  `pool_timeout`, `read_timeout`, `disconnected` — infrastructure failures where
  the request plausibly never ran. A `read_timeout` *after* bytes were sent is the
  riskiest of these, which is exactly why the idempotency gate below exists.

```python
from clientwright import FailureKind

RetryConfig(
    retryable_status=frozenset({429, 503}),
    retryable_kinds=frozenset({FailureKind.CONNECT_ERROR, FailureKind.CONNECT_TIMEOUT}),
)
```

## The gates a retry must pass

A retry-worthy failure is necessary but not sufficient. In order:

1. **Attempts left.** `len(history) < max_attempts`.
2. **Idempotency.** `GET`, `HEAD`, `PUT`, `DELETE`, `OPTIONS`, `TRACE` pass by
   method. A `POST` is refused — unless the *call site* vouches for it via the
   [per-call idempotency flag](per-call-options.md), which is the honest place for
   that knowledge to live.
3. **Replayable body.** Before the first send the engine freezes the request body
   (buffers a stream, if there is one). A body that cannot be replayed — a one-shot
   generator, an open socket — vetoes every repeat. No half-sent uploads, ever.
4. **The deadline.** A backoff sleep that would land past the remaining total is
   pointless; the engine returns the failure now instead of burning the budget.
5. **The retry budget.** See below.

Every refusal by gates 2–5 emits a `http_client_retry_skipped_total` counter with
the reason (`method`, `non_replayable`, `deadline`, `budget`) — when a retry you
expected did not happen, the metric says why.

## Backoff, `Retry-After`, and the budget

Delay is exponential with jitter, capped by `max_backoff`. If the response carried
`Retry-After` (seconds or HTTP-date), the server's number wins — capped by
`retry_after_max` (60 s by default) so a hostile header cannot park your worker.

The **retry budget** is the anti-retry-storm device: a token bucket per origin.
Every call earns `budget_ratio` tokens (0.1 by default), every retry spends one —
so sustained retry traffic cannot exceed roughly 10 % of real traffic per origin.
When the upstream is truly down, retries stop amplifying the outage while the
[circuit breaker](circuit-breaker.md) takes over. Set `budget_ratio=None` to
disable (you probably should not).

## One logical call, whatever happens inside

However many attempts and redirect hops the engine performs, your code sees one
call and the telemetry counts one `http_client_requests_total` — with
`http_client_attempts_total` telling the inner story. Failed responses are drained
before a repeat so their connections return to the pool; request bodies are
rewound; the final outcome (success or the *last* failure) is what you and the
circuit breaker observe.

## Delegated mode

One adapter — urllib3 — ships a real native retry engine, and some codebases have
operational muscle memory around it. `RetryMode.DELEGATED` hands the loop down:

```python
from clientwright import RetryConfig, RetryMode

RetryConfig(max_attempts=3, mode=RetryMode.DELEGATED)  # urllib3 only
```

The config is translated into a `urllib3.util.Retry`, and — capability honesty —
`http_client_attempts_total` is *not* emitted, because the attempts happen below
the seam where the engine cannot see them. Details in the
[urllib3 adapter page](../adapters/urllib3.md).
