"""Structural lint: doc_types.REGISTRY is the single source of truth.

Per the "if you can't write a lint rule for it, it's not a golden principle"
philosophy, this test is the lint behind the registry source-of-truth
principle in kb/reins/golden-principles.md.

Prefer ruff-native enforcement when the rule is expressible there (e.g. the
sanitize_branch confinement lives in pyproject.toml as a TID251 banned-api).
Hand-rolled AST checks like this one are a fallback for rules ruff cannot
express. If we accumulate several more of them (here or in
test_output_conventions.py), stop and build a proper flake8 plugin (or
semgrep rules) instead of growing this file.
"""

from __future__ import annotations

import ast
from pathlib import Path

from reinicorn.doc_types import REGISTRY

SRC = Path(__file__).resolve().parent.parent / "src" / "reinicorn"
DOC_TYPE_KEYS = frozenset(REGISTRY)


def _modules() -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text()))
        for path in sorted(SRC.rglob("*.py"))
        if path.name != "doc_types.py"
    ]


def _constant_strings(node: ast.expr) -> list[str]:
    """String constants in a comparator: bare, or inside a tuple/list/set literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [
            e.value
            for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
    return []


def test_no_doc_type_key_comparisons() -> None:
    """Per-type behavior is driven by registry fields, not key comparisons.

    `REGISTRY["spec"]` lookups consult the registry and are fine; branching on
    `doc_type == "spec"` duplicates type knowledge in control flow and is not.
    """
    violations = []
    for path, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            for operand in (node.left, *node.comparators):
                keys = DOC_TYPE_KEYS.intersection(_constant_strings(operand))
                if keys:
                    violations.append(
                        f"{path.relative_to(SRC)}:{node.lineno}"
                        f" compares against {sorted(keys)}"
                    )
    assert not violations, (
        "doc-type keys in control-flow comparisons "
        "(drive behavior from registry fields instead):\n" + "\n".join(violations)
    )
