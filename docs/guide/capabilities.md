# Capability honesty

Five SDKs, one config — something has to give. Most portability layers give up
quietly: the option you set does nothing on backend X, and you find out during an
incident. clientwright's alternative is a capability model with three moving
parts: a **declaration** per adapter, a **report** per build, and a **policy**
that decides how loud a mismatch is.

## The declaration

Every adapter ships a frozen `AdapterCapabilities` record — importable *without*
the SDK installed:

```python
import clientwright

caps = clientwright.capabilities_matrix()["aiohttp"]

print(caps.seam)  # 'middleware' — where the engine is installed
print(caps.support)  # Capability -> native | emulated | degraded | absent
print(caps.emits)  # which FailureKinds this adapter can actually produce
print(caps.collapses)  # finer kinds that fold into coarser ones here
```

Four support levels, honestly graded:

| Level | Meaning |
|---|---|
| `native` | the SDK expresses it itself |
| `emulated` | the engine provides it on top (e.g. per-host limits via a semaphore) |
| `degraded` | works, with a stated weaker guarantee (e.g. soft deadlines on sync) |
| `absent` | not available; config asking for it is dropped |

`emits` and `collapses` extend the honesty to *failure taxonomy*: an adapter that
cannot distinguish DNS errors from connect errors says so, instead of inventing a
distinction it cannot observe.

## The report

Building a client evaluates your config against the declaration and attaches the
verdict to the handle:

```python
handle = clientwright.build_handle("requests", config)

handle.report.applied_natively  # what the SDK expressed itself
handle.report.emulated  # what the engine added on top
handle.report.dropped  # {Capability: reason} — could not be honored
handle.report.dead_retryable_kinds  # retry triggers this adapter can never emit
handle.report.native_overrides  # accepted native passthrough, per slot
```

`dead_retryable_kinds` deserves a sentence: if your retry policy waits for
`dns_error` but the adapter never emits it, that trigger is *dead* — configured,
believed in, and impossible. The report says so at build time instead of letting
you discover it from a graph that never moves.

## The policy

`on_unsupported` turns the report into behavior:

```python
from clientwright import ClientConfig, UnsupportedPolicy

ClientConfig(service_name="x", on_unsupported=UnsupportedPolicy.STRICT)  # raise at build
ClientConfig(service_name="x", on_unsupported=UnsupportedPolicy.WARN)  # log, continue (default)
ClientConfig(service_name="x", on_unsupported=UnsupportedPolicy.IGNORE)  # silence
```

The house recommendation: **`STRICT` in production configs.** A service that
starts is a service whose config is fully in effect; a dropped knob becomes a
failed deploy instead of a false belief. `WARN` is the forgiving default for
exploration; `IGNORE` is for the rare config that is deliberately shared across
adapters with known, accepted gaps.

## Reading the matrix before you commit

Because declarations import without SDKs, you can diff adapters ahead of a
migration:

```python
matrix = clientwright.capabilities_matrix()
for name, caps in matrix.items():
    print(name, caps.support_of(clientwright.Capability.HTTP2))
```

That, plus the [adapter pages](../adapters/index.md), is the whole decision
input for "can we move this service from requests to httpx" — no folklore
required.
