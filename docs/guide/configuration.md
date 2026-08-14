# Configuration

Everything a client is lives in one frozen dataclass:

```python
from clientwright import (
    CircuitBreakerConfig,
    ClientConfig,
    ObservabilityConfig,
    RetryConfig,
    TimeoutConfig,
)

config = ClientConfig(
    service_name="identity",  # required, everything else optional
    base_url="https://accounts.example.com",
    timeout=TimeoutConfig(total=10.0, connect=2.0),
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(fail_threshold=5),
    headers={"User-Agent": "identity/2.3"},
    observability=ObservabilityConfig(),
    on_unsupported="strict",
)
```

`ClientConfig` is transport-free on purpose: no `httpx.Timeout`, no
`aiohttp.ClientTimeout`, no SDK type anywhere. The same object is readable by every
adapter, which is what makes "swap the adapter, keep the config" real.

## Defaults are production-shaped

An empty config is not a neutral config. Out of the box you get:

| Concern | Default |
|---|---|
| Total deadline | 30 s wall clock, `connect` capped at 5 s |
| Retries | 3 attempts, exponential backoff 0.1 s → 10 s, 20 % jitter, `Retry-After` respected |
| Retry budget | at most ~10 % of an origin's traffic may be retries |
| Circuit breaker | opens after 5 qualifying failures per origin, 60 s recovery |
| Redirects | owned by the engine, at most 5 hops |
| Observability | logs, metrics and traces on; secrets redacted |

Disabling is always explicit and always `None`:

```python
config = ClientConfig(service_name="batch", retry=None, circuit_breaker=None)
```

## `UNSET` is not `None`

Config fields that map onto an SDK knob distinguish three states:

```python
from clientwright import UNSET, TimeoutConfig

TimeoutConfig(read=5.0)  # you chose 5 seconds
TimeoutConfig(read=None)  # you chose "no read timeout" - explicitly unlimited
TimeoutConfig(read=UNSET)  # you chose nothing: the adapter's native default applies
```

`UNSET` (the default) means *defer to the library you picked* — and that deferral
is visible in the build [report](capabilities.md) rather than silently guessed.
This is what lets clientwright avoid inventing its own opinion for every knob of
five different SDKs.

## Validation happens at construction

Bad values fail where you typed them, not three layers later:

```python
ClientConfig(service_name="x", base_url="ftp://nope")  # ValueError: http(s) only
TimeoutConfig(total=0)  # ValueError: must be positive
RetryConfig(jitter=1.5)  # ValueError: within [0, 1]
```

## From service settings

Services usually keep settings in a pydantic model. Rather than depending on
pydantic, clientwright accepts anything that structurally matches
`ClientSettingsProtocol` — attribute names, not base classes:

```python
from clientwright import client_config_from_settings

config = client_config_from_settings(settings.warehouse_api, "orders")
```

Map your settings into a `ClientConfig` in exactly one place (usually next to the
DI wiring) and pass the result around. The config is frozen, so it is safe to share.

## The rest of the surface

Each remaining field has its own page:

- `timeout`, `caller_override`, `deadline_header` → [Timeouts and deadlines](timeouts.md)
- `retry` → [Retries](retries.md)
- `circuit_breaker` → [Circuit breaker](circuit-breaker.md)
- `redirects`, `max_redirects` → [Redirects](redirects.md)
- `observability` → [Observability](observability.md)
- `tls`, `proxy` → [Proxies and TLS](proxies-tls.md)
- `native` → [Native passthrough](native-options.md)
- `on_unsupported` → [Capability honesty](capabilities.md)
- `pool` → mostly self-describing (`max_connections`, `max_keepalive`,
  `keepalive_expiry`, `max_connections_per_host`, `http2`); per-host limits are
  emulated with a per-origin semaphore on adapters whose pools cannot express them.
