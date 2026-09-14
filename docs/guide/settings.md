# Environment settings

The part of a client that differs between dev, stage and prod — base URL, timeouts,
pool size, HTTP/2, retry and breaker policy — is exactly the part that has to come
from the environment. With `clientwright[settings]` that path is owned by the
library: one pydantic model per config dataclass, the same field names and the same
defaults, and `to_config()` to get the `ClientConfig`.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

from clientwright import build
from clientwright.contrib.settings import BaseClientSettings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")

    warehouse: BaseClientSettings = BaseClientSettings()
    identity: BaseClientSettings = BaseClientSettings()


settings = Settings()
client = build("httpx", settings.warehouse.to_config("warehouse"))
```

```bash
WAREHOUSE__BASE_URL=https://wh.example.com
WAREHOUSE__TIMEOUT__TOTAL=10
WAREHOUSE__TIMEOUT__CONNECT=2
WAREHOUSE__POOL__HTTP2=true
WAREHOUSE__RETRY__MAX_ATTEMPTS=5
WAREHOUSE__RETRY__RETRYABLE_STATUS=[429,500,502,503,504]
WAREHOUSE__CIRCUIT_BREAKER__FAIL_THRESHOLD=2
WAREHOUSE__ON_UNSUPPORTED=strict
```

One section per sub-config, named as the config names it:

| Section | Model | Builds |
|---|---|---|
| the client itself | `BaseClientSettings` | `ClientConfig` |
| `timeout` | `BaseTimeoutSettings` | `TimeoutConfig` |
| `pool` | `BasePoolSettings` | `PoolConfig` |
| `retry` | `BaseRetrySettings` | `RetryConfig` |
| `circuit_breaker` | `BaseCircuitBreakerSettings` | `CircuitBreakerConfig` |
| `tls` | `BaseTlsSettings` | `TlsConfig` |
| `proxy` | `BaseProxySettings` | `ProxyConfig` |
| `observability` | `BaseObservabilitySettings` | `ObservabilityConfig` |

The field names, types and defaults are the dataclasses' — the test suite asserts
`BaseClientSettings().to_config("x") == ClientConfig(service_name="x")` and compares
the field names of every pair, so the models cannot drift from
[the config](configuration.md) they describe.

## Sections are models, not settings

Every class in `clientwright.contrib.settings` is a plain pydantic `BaseModel`,
never a `BaseSettings`. That is deliberate. A `BaseSettings` scrapes the environment
on its own, and one written per section scrapes it **with no prefix** — a bare
`BASE_URL` or `TIMEOUT` set anywhere in the pod lands in a nested client section
its parent never filled. A `BaseModel` is reachable only through the settings object
you nest it in, so the only way into `warehouse.timeout.total` is
`WAREHOUSE__TIMEOUT__TOTAL`.

The parent is yours: its prefix, its `env_nested_delimiter`, its `.env` file, how
many client sections it holds. Subclass a model to change a default for one
upstream, and narrow a section to `None` to switch it off:

```python
from clientwright.contrib.settings import BaseClientSettings, BaseTimeoutSettings


class BatchApi(BaseClientSettings):
    timeout: BaseTimeoutSettings = BaseTimeoutSettings(total=120.0)
    retry: None = None
    circuit_breaker: None = None
```

## What maps how

- **`service_name` is the argument of `to_config()`**, not a field. It is the
  `service` label on every metric and log line — code identity, not something a
  deployment changes.
- **`UNSET` survives.** A knob the config leaves `UNSET` by default (`timeout.read`,
  `timeout.attempt`, `pool.http2`, `pool.max_connections_per_host`, ...) reaches
  the config as `UNSET` unless you set it — the adapter's native default, exactly as
  when you write `TimeoutConfig()` yourself. An explicit `null` is the dataclass'
  explicit "unbounded": `WAREHOUSE__TIMEOUT__READ=null` needs
  `env_parse_none_str="null"` on the parent, while a whole section
  (`WAREHOUSE__RETRY=null`) is parsed as JSON and needs nothing.
- **Enums by value**: `RETRY__MODE=delegated`, `CIRCUIT_BREAKER__KEY=origin_route`,
  `REDIRECTS=native`, `ON_UNSUPPORTED=strict`. A typo fails at load.
- **Sets as JSON lists**: `RETRY__RETRYABLE_STATUS=[429,500]`,
  `RETRY__RETRYABLE_KINDS=["dns_error","connect_error"]`,
  `OBSERVABILITY__SENSITIVE_QUERY_PARAMS=["token"]`.
- **`success_log_level` by name or number**: `OBSERVABILITY__SUCCESS_LOG_LEVEL=DEBUG`.
- **`headers` and `native` as JSON objects**: `HEADERS={"User-Agent": "orders/2.3"}`,
  `NATIVE={"client": {"trust_env": false}}` — the latter is validated at build like
  any [native passthrough](native-options.md).
- **`tls.cert`** is a PEM path, or a JSON list of two or three paths for
  `(cert, key)` / `(cert, key, password)`.
- **`proxy`** is `None` until any of its fields is set: `PROXY__URL=http://proxy:3128`
  creates the section; `PROXY__FROM_ENV=true` reads the environment's proxies.
- **`observability.url_masker`** is a callable and has no environment spelling. Set
  it on the config afterwards:

    ```python
    from dataclasses import replace

    config = settings.identity.to_config("identity")
    config = replace(config, observability=replace(config.observability, url_masker=mask_emails))
    ```

Bounds are validated at load, with the field path in the error — `timeout.total`
must be positive, `retry.max_attempts >= 1`, `proxy.url` and `proxy.from_env` are
exclusive — so a bad value fails where the deployment set it, not three layers later.
The dataclass validates once more in `to_config()`, so nothing gets past both.

## Without pydantic

`ClientSettingsProtocol` and `client_config_from_settings(settings, service_name)`
accept any object with the flat, legacy attribute names (`timeout_seconds`,
`enable_http2`, a four-field `retry`, a three-field `circuit_breaker`) — no base
class and no extra required. Keep it for a service that already carries a settings
model of that shape; write new code against the models above.
