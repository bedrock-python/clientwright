"""Family parity: httpx and httpx2 expose IDENTICAL public names.

Checked with AST, not imports, so the test needs NEITHER SDK installed - the
same trick servicewright uses for its scheduler conformance.
"""

from __future__ import annotations

import ast
from pathlib import Path

import clientwright

FAMILY_ROOT = Path(clientwright.__file__).parent / "adapters"


def module_all(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    value = ast.literal_eval(node.value)
                    assert isinstance(value, list)
                    return value
    raise AssertionError(f"{path} has no literal __all__")


def class_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def test__public_api__identical_between_httpx_and_httpx2() -> None:
    httpx_all = module_all(FAMILY_ROOT / "httpx" / "__init__.py")
    httpx2_all = module_all(FAMILY_ROOT / "httpx2" / "__init__.py")
    assert httpx_all == httpx2_all  # migration = one extra and one import path


def test__module_files__mirror_each_other() -> None:
    httpx_files = {p.name for p in (FAMILY_ROOT / "httpx").glob("*.py")}
    httpx2_files = {p.name for p in (FAMILY_ROOT / "httpx2").glob("*.py")}
    assert httpx_files == httpx2_files


def test__per_module_public_names__match() -> None:
    for name in ("views.py", "transport.py", "errors.py", "normalize.py", "normalize_sync.py"):
        httpx_names = module_all(FAMILY_ROOT / "httpx" / name)
        httpx2_names = module_all(FAMILY_ROOT / "httpx2" / name)
        assert httpx_names == httpx2_names, f"{name} diverged"


def test__both_adapters__define_the_same_adapter_class_name() -> None:
    assert "HttpxAdapter" in class_names(FAMILY_ROOT / "httpx" / "adapter.py")
    assert "HttpxAdapter" in class_names(FAMILY_ROOT / "httpx2" / "adapter.py")


def test__capability_records__differ_only_in_adapter_identity() -> None:
    matrix = clientwright.capabilities_matrix()
    httpx_caps = matrix["httpx"]
    httpx2_caps = matrix["httpx2"]
    assert httpx2_caps.adapter == "httpx2"
    assert httpx2_caps.seam == httpx_caps.seam
    assert httpx2_caps.support == httpx_caps.support
    assert httpx2_caps.emits == httpx_caps.emits
    assert httpx2_caps.collapses == httpx_caps.collapses
