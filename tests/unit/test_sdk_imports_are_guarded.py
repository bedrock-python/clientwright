"""No test module may import an SDK without an ``importorskip`` guard.

pytest imports every test file during collection, before markers deselect
anything - so one bare ``import httpx`` breaks the whole run in an environment
without that extra, including the core-only CI job. The dev environment has all
extras installed, which is exactly why this needs a static check rather than a
runtime one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
SDK_ROOTS = frozenset(
    {
        "httpx",
        "httpx2",
        "aiohttp",
        "requests",
        "urllib3",
        "dishka",
        "prometheus_client",
        "opentelemetry",
        "deadline_budget",
    }
)


def _guarded_before(tree: ast.Module, lineno: int) -> set[str]:
    """SDK names an ``importorskip`` call has already vouched for by ``lineno``."""
    guarded: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or node.lineno >= lineno:
            continue
        target = node.func
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", None)
        if name != "importorskip" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            guarded.add(first.value.split(".")[0])
    return guarded


def _unguarded_sdk_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.iter_child_nodes(tree):  # module level only
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots = [node.module.split(".")[0]]
        else:
            continue
        for root in roots:
            if root in SDK_ROOTS and root not in _guarded_before(tree, node.lineno):
                offenders.append(f"{path.name}:{node.lineno} imports {root!r}")
    return offenders


TEST_FILES = sorted(TESTS_DIR.rglob("*.py"))


def test__the_scan__actually_sees_the_suite() -> None:
    assert len(TEST_FILES) > 30


@pytest.mark.parametrize("path", TEST_FILES, ids=[str(p.relative_to(TESTS_DIR)) for p in TEST_FILES])
def test__module_level_sdk_imports__sit_behind_importorskip(path: Path) -> None:
    offenders = _unguarded_sdk_imports(path)
    assert not offenders, (
        "unguarded SDK import breaks collection without that extra; "
        "use `sdk = pytest.importorskip(...)` first: " + "; ".join(offenders)
    )
