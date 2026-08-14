# Contributing to clientwright

Thank you for your interest in contributing! This document covers everything you need to get started.

## Development setup

```bash
git clone https://github.com/bedrock-python/clientwright.git
cd clientwright
uv sync --group dev --all-extras
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
```

## Running checks

```bash
make fmt              # ruff format + ruff check --fix
make check            # ruff lint + format check + mypy + import-linter contracts
make test-unit        # unit tests
make test-integration # integration tests against an in-process origin server
make test             # full suite with the 97% coverage threshold
```

No Docker anywhere: the integration suite starts its own HTTP origin in-process.
The `import-linter` contracts in `make check` are load-bearing — they are what
keeps `core/` free of adapter and SDK imports.

Tests that hit the public internet are opt-in and never run by default:

```bash
make test-live        # or: uv run pytest tests/live --live
```

## Code style

- **Type hints** on all functions and methods, including tests
- **Docstrings** on public API only — Google style
- **Line length** — 120 characters (ruff enforced)
- **Quotes** — double quotes (ruff enforced)
- **No comments** unless the *why* is non-obvious

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/) are enforced by pre-commit:

| Prefix | Use for |
|--------|---------|
| `feat:` | New feature or behaviour |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `test:` | Test additions or changes |
| `refactor:` | Code restructure, no behaviour change |
| `perf:` | Performance improvement |
| `chore:` | Build, tooling, CI |

Breaking changes: add `!` after the type (`feat!:`) or include a `BREAKING CHANGE:` footer.

## Pull requests

1. Fork the repository
2. Create a branch from `master`: `git checkout -b feat/my-feature`
3. Make your changes with tests
4. Run `make check && make test-unit` locally
5. Open a PR against `master`

## Releasing (maintainers only)

Releases are fully automated via [Release Please](https://github.com/googleapis/release-please).
Merge a PR with conventional commits → Release Please creates a release PR → merge it → PyPI publish happens automatically.
