"""Documentation snippets must not rot.

Every fenced ``python`` block in docs/ has to (a) parse as real Python and
(b) import only names that actually exist in clientwright. This does not execute
snippets - it kills the two most common documentation lies: syntax that never
ran and APIs that were renamed after the page was written.
"""

from __future__ import annotations

import ast
import importlib
import re
import textwrap
from pathlib import Path

import pytest

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
# Content-tab snippets are indented together with their fence; capture the fence
# indent and dedent the body by it.
FENCE = re.compile(r"(?m)^(?P<indent>[ \t]*)```python\n(?P<body>.*?)^(?P=indent)```", re.DOTALL)


def _python_blocks() -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for page in sorted(DOCS_DIR.rglob("*.md")):
        text = page.read_text(encoding="utf-8")
        for index, match in enumerate(FENCE.finditer(text), start=1):
            source = textwrap.dedent(match.group("body"))
            blocks.append((f"{page.relative_to(DOCS_DIR).as_posix()}#{index}", source))
    return blocks


BLOCKS = _python_blocks()


def test__docs__contain_python_snippets_at_all() -> None:
    assert len(BLOCKS) > 30  # the docs are example-driven; an empty crawl means the regex broke


@pytest.mark.parametrize(("block_id", "source"), BLOCKS, ids=[block_id for block_id, _ in BLOCKS])
def test__snippet__parses_and_its_clientwright_imports_resolve(block_id: str, source: str) -> None:
    tree = compile(source, block_id, "exec", flags=ast.PyCF_ONLY_AST | ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module is None or not node.module.startswith("clientwright"):
            continue
        try:
            module = importlib.import_module(node.module)
        except ImportError:
            pytest.skip(f"{node.module} needs an extra that is not installed here")
        for alias in node.names:
            try:
                getattr(module, alias.name)
            except ImportError:
                pytest.skip(f"{node.module}.{alias.name} needs an extra that is not installed here")
            except AttributeError:
                raise AssertionError(f"{block_id}: documented name {node.module}.{alias.name} does not exist") from None
