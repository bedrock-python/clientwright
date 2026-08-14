# Native passthrough

`ClientConfig` covers what is portable. Sometimes you need the knob that is not:
httpx's `http1=False`, aiohttp's `trust_env`, a connector setting the config never
heard of. `NativeOptions` is the escape hatch — raw keyword arguments passed to
the native constructors, **validated instead of forwarded blindly**.

```python
from clientwright import ClientConfig, NativeOptions

config = ClientConfig(
    service_name="orders",
    native=NativeOptions.of(
        client={"trust_env": False},  # goes into the SDK client constructor
    ),
)
```

## Slots

Every adapter declares named *slots* — the constructors it can forward into
(`client` everywhere; adapters with a separate transport/connector object expose
that too). `NativeOptions.of(slot_name={...})` targets one slot. An unknown slot
name is a build-time error listing the adapter's real slots.

## Validation, not vibes

Passthrough is where config systems usually rot: a typo becomes a silently
ignored kwarg, an option collides with what the engine already set, and six
months later nobody knows which timeout actually applies. clientwright checks
all three at build time:

- **Unknown key** → error, with a did-you-mean suggestion from the constructor's
  real signature.
- **Reserved key** → error. Knobs the engine owns (`timeout`, `transport`,
  redirect switches, retry machinery) cannot be smuggled in underneath it; the
  error names the config field that owns the concern.
- **Conflict** → error when a native key duplicates a `ClientConfig` field you
  also set explicitly. One source of truth per knob, enforced.

What was *accepted* is visible too: `handle.report.native_overrides` lists every
native key applied per slot, so a build's full story — portable config plus
passthrough — is one inspectable object.

!!! tip "Reach for it late"

    If a native option is portable in spirit (a timeout, a pool size, a TLS
    setting), it probably belongs in `ClientConfig` — file an issue. `native` is
    for the genuinely SDK-specific tail, and every use of it is an explicit
    non-portability marker in your codebase.
