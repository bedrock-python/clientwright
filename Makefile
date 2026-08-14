.PHONY: test test-unit test-integration test-live fmt check build install docs-serve docs-build clean

install:
	uv sync --group dev

fmt:
	uv run ruff format .
	uv run ruff check --fix .

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy clientwright
	uv run lint-imports

test-unit:
	uv run pytest -m unit

test-integration:
	uv run pytest -m integration

# Hits real third-party endpoints; never part of `make test` or of CI gating.
test-live:
	uv run pytest tests/live --live --no-cov

test:
	uv run pytest --cov=clientwright --cov-report=term --cov-fail-under=97 --cov-report=xml:coverage.xml

build:
	uv build

docs-serve:
	python -c "import shutil; shutil.copy('CHANGELOG.md', 'docs/changelog.md')"
	uv run --no-dev --group docs zensical serve

docs-build:
	python -c "import shutil; shutil.copy('CHANGELOG.md', 'docs/changelog.md')"
	uv run --no-dev --group docs zensical build --clean

clean:
	python -c "import shutil, os, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['.pytest_cache', '.mypy_cache', '.ruff_cache', 'dist', 'build', 'site'] if os.path.exists(p)]; [os.remove(p) for p in ['.coverage', 'coverage.xml'] if os.path.exists(p)]; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
