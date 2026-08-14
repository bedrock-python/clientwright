# API Reference

Auto-generated from source docstrings. The prose lives in the
[Guide](../guide/configuration.md); these pages are the precise surface.

| Page | Covers |
|---|---|
| [Core](core.md) | `build` / `build_sync` / `inspect`, `ClientConfig` and all sub-configs, the data model, errors, capabilities, plans and runtime |
| [Adapters](adapters.md) | per-adapter public exports: per-call channels and dual-family errors |
| [Contrib](contrib.md) | deadline-budget and dishka integrations |
| [Testing](testing.md) | `OriginServer`, `RecordingMetrics`, `ManualClock` |

## What is stable

Under semver, the public API is exactly:

- the names in `clientwright.__all__`,
- the names in each adapter package's `__all__` (`clientwright.adapters.*`),
- `clientwright.contrib.*` and `clientwright.core.testing`.

Everything else below `clientwright.core` is internal machinery — documented
here where it explains behavior, but free to change. Anything prefixed with `_`
is internal everywhere.

While the version is `0.x`, minor releases may still contain breaking changes;
they will be called out in the changelog.
