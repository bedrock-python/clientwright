# Proxies and TLS

Both knobs are deliberately small: they cover the shapes every SDK can express,
and anything an SDK cannot express is [reported](capabilities.md) instead of
faked.

## TLS

```python
from clientwright import ClientConfig, TlsConfig

config = ClientConfig(
    service_name="ledger",
    tls=TlsConfig(
        verify=True,  # the default; False is for dev only
        ca_bundle="/etc/ssl/internal.pem",  # private CA
        cert=("/etc/ssl/client.crt", "/etc/ssl/client.key"),  # mTLS
    ),
)
```

- `verify=False` disables certificate verification — it exists for local
  environments and is exactly as dangerous as it sounds.
- `ca_bundle` points verification at your CA file instead of the system store.
- `cert` is a client certificate: a single path to a combined PEM or a
  `(cert, key)` tuple. A three-element form with a key password is accepted by
  the type but only where the SDK supports it — elsewhere it fails the build
  honestly rather than sending an unprotected key.

## Proxies

```python
from clientwright import ClientConfig, ProxyConfig

explicit = ClientConfig(
    service_name="crawler",
    proxy=ProxyConfig(url="http://proxy.internal:3128"),
)

from_env = ClientConfig(
    service_name="crawler",
    proxy=ProxyConfig(from_env=True),  # honor HTTP(S)_PROXY / NO_PROXY
)
```

The two modes are mutually exclusive by construction — a config that sets both
raises at creation. The default is **no proxy at all**, including ignoring the
environment: an HTTP client that silently changes its network path because a
deploy script exported `HTTPS_PROXY` is a debugging story nobody wants twice.
`from_env=True` opts back into the conventional behavior, including `NO_PROXY`
bypass rules.

How each SDK realizes the routing differs (httpx uses per-scheme mounts, urllib3
swaps in a genuine `ProxyManager`, and so on) — see the adapter pages for the
mechanics and the honest limitations. What does *not* differ: a proxy configured
here applies to every request of the client, and a proxy the adapter cannot
express in the requested mode lands in `report.dropped` with the reason.
