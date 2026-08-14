# Writing an adapter

An adapter is smaller than it sounds: find the seam, translate the messages,
classify the errors, declare the truth. The engine, policies, telemetry and test
instruments are already written. Existing adapters run 300–600 lines including
docstrings; budget a similar order for yours.

This page sketches the shape. The precise contracts live in
`clientwright.core.contracts` and are enforced structurally — implement the
methods and you are in, no base classes.

## 1. Find the seam

The seam is the place in *your* SDK where every request passes and where you can
act **under** the public API. Transport slot, middleware chain, adapter mount,
method wrap — in that order of preference. Two hard requirements:

- the native client object handed to users stays genuine (`type(...)` should
  ideally be the SDK's own class), and
- there is either no bypass around the seam, or the bypass is detectable so you
  can count it (see aiohttp's `uninstrumented_calls` sentinel).

## 2. Implement the views and the normalizer

```python
class MyRequestView:  # RequestView protocol
    native: ...  # the SDK's request object
    info: RequestInfo  # method, origin, url, route, idempotent
    headers: MutableMapping[str, str]

    def caller_timeouts(self) -> ResolvedTimeouts | None: ...
    def apply_timeouts(self, planned: ResolvedTimeouts) -> None: ...
    def retarget(self, url, *, method=None, drop_body=False) -> None: ...
```

The normalizer wraps native request/response objects into views, maps the SDK's
exceptions onto `FailureKind`, and implements the three body operations —
`freeze` / `rewind` / `discard`. Classification is where correctness bugs hide:
mind your SDK's exception *inheritance* (clientwright's own test campaign caught
a ladder ordered wrong for urllib3 v2, where DNS errors subclass connect
timeouts). Write the classification tests first.

## 3. Build and wire

Your adapter class exposes `build_async` and/or `build_sync`: construct the
native client from `ClientConfig` (respecting `UNSET` = native default), install
the engine at the seam, compile the plan, register the handle, and return a
`ClientHandle`. Translate engine errors into dual-family classes
(`class MyCircuitOpenError(CircuitOpenError, my_sdk.Error)`), so both `except`
styles work.

## 4. Declare capabilities

```python
CAPABILITIES = AdapterCapabilities(
    adapter="myhttp",
    seam="transport",
    granularity=SeamGranularity.LOGICAL,
    boundary=DurationBoundary.FULL,
    support={Capability.TIMEOUT_CONNECT: Support.NATIVE},  # the full matrix, honestly graded
    emits=frozenset({FailureKind.CONNECT_ERROR, FailureKind.READ_TIMEOUT}),
    collapses={FailureKind.DNS_ERROR: FailureKind.CONNECT_ERROR},
)
```

This module must import **without the SDK installed** — it is what
`capabilities_matrix()` shows to users deciding whether to adopt you. Understate
rather than overstate: `dropped` with a reason beats a knob that silently does
nothing.

## 5. Register and test

```python
import clientwright

clientwright.register_adapter(
    "myhttp",
    "my_pkg.adapter:MyHttpAdapter",
    "my_pkg.capabilities:CAPABILITIES",
)
```

Lazy string targets keep your SDK unimported until first build. For tests, point
your client at `clientwright.core.testing.OriginServer` and work through the
[chaos routes](../guide/testing.md#integration-tests-a-fault-injecting-origin):
the flaky route proves your retries, `/redirect/2` proves retargeting,
`/drop-body` and `/garbage` prove your error classification, and
`RecordingMetrics.inflight_balance == 0` after every failure proves your seam
closes telemetry on all paths. If clientwright's in-tree parity scenarios pass
against your adapter, you have earned the same guarantees the built-ins claim.
