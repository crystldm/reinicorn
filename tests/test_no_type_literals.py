"""The executable form of spec §2b: no type names in the engine.

Walks every module under ``src/reinicorn`` except the defaults table
(``doc_types.py``) and fails on any identifier or string literal carrying a
word equal to a built-in type key. Tests may still name the defaults — they
are the fixture.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from reinicorn.doc_types import REGISTRY

SRC = Path(__file__).parent.parent / "src" / "reinicorn"
TYPE_KEYS = frozenset(REGISTRY)

# The defaults table is the one sanctioned home for type keys.
EXCLUDED_MODULES = {"doc_types.py"}

# Each entry is a deliberate, documented exception, not a loophole.
ALLOWED_STRINGS = {
    # Lint rule names are enablement keys in deployed
    # ``linters/.lint-config.json`` files — renaming one silently disables
    # it (the runner skips unconfigured rules). Config-compat surface.
    "/plan-structure",
    # English usage of "idea" (feedback to the maintainers), not the doc type.
    "Report a bug or idea",
    "Describe the issue or idea: ",
    # "plan" = GitHub billing plan, not the doc type.
    "ruleset update failed (plan/permissions?) — Reinicorn's own divergence "
    "check remains the guardrail",
    "ruleset not applied (plan/permissions?) — Reinicorn's own divergence "
    "check remains the guardrail",
    # Cites a governance document by its review lane, prose not behavior.
    "' is not a 40-hex commit SHA.\n  Tags are not valid pins — resolve the "
    "tag to its commit and pin that (see spec: skill-base-agnostic adapter "
    "source rules).",
}

_WORD_RE = re.compile(r"[a-z]+")


def _words(token: str) -> set[str]:
    """Lower-cased alphabetic words in an identifier or string."""
    return set(_WORD_RE.findall(token.lower()))


def _offending_words(token: str) -> set[str]:
    return _words(token) & TYPE_KEYS


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """id()s of the Constant nodes that are docstrings.

    Docstrings are documentation, not engine behavior: prose citing a spec
    document or using an English word that happens to be a type key does
    not couple code to the type.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            ids.add(id(body[0].value))
    return ids


def _check_module(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    docstrings = _docstring_nodes(tree)
    findings: list[str] = []

    def report(node: ast.AST, kind: str, token: str) -> None:
        hits = _offending_words(token)
        if hits:
            findings.append(
                f"{path.name}:{node.lineno} {kind} {token!r} "
                f"names type key(s) {sorted(hits)}"
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in ALLOWED_STRINGS or id(node) in docstrings:
                continue
            report(node, "string", node.value)
        elif isinstance(node, ast.Name):
            report(node, "name", node.id)
        elif isinstance(node, ast.Attribute):
            report(node, "attribute", node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            report(node, "def", node.name)
        elif isinstance(node, ast.arg):
            report(node, "arg", node.arg)
        elif isinstance(node, ast.alias):
            report(node, "import", node.asname or node.name)
        elif isinstance(node, ast.keyword) and node.arg:
            report(node, "kwarg", node.arg)

    return findings


@pytest.mark.parametrize(
    "module",
    sorted(
        (p for p in SRC.rglob("*.py") if p.name not in EXCLUDED_MODULES),
        key=lambda p: p.as_posix(),
    ),
    ids=lambda p: p.relative_to(SRC).as_posix(),
)
def test_no_type_key_literals(module: Path):
    findings = _check_module(module)
    assert not findings, "\n".join(findings)
