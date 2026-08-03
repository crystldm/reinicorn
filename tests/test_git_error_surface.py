"""Structural lint: git failures are turned into text in exactly one place.

Per the "if you can't write a lint rule for it, it's not a golden principle"
philosophy, this is the lint behind the seam in reinicorn.git. Six modules used
to read `.stderr` off a git result and invent their own shape; one of them
substituted "kb has conflicting changes" for an authentication error and sent
the reader into a retry loop. A single ad-hoc format is enough to lose that
again, so the rule is mechanical rather than a convention.

RUFF-NATIVE FIRST: as test_source_of_truth.py says, prefer ruff when the rule
is expressible there. This one is not — ruff's TID251 bans *imported names*
(`reinicorn.git.sanitize_branch`), and `result.stderr` is attribute access on a
local, which no ruff rule matches.

THRESHOLD: this is the third hand-rolled AST check in the suite
(test_source_of_truth.py has two). That file says to stop and build a proper
flake8 plugin or semgrep rules once several accumulate. We are there. Do not
add a fourth by hand — port all three to semgrep instead. Kept hand-rolled
here only because leaving the invariant unenforced while tooling is chosen is
strictly worse than one more walker.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "reinicorn"

#: The module that owns git-failure→message conversion, as a path relative to
#: the package root.
SEAM = "git.py"

#: One owner per external CLI. git.py wraps git; github.py's `run_gh` is the
#: single place gh's stderr becomes a message. Two tools, two seams — but only
#: these two, which is what the tests below pin down.
#:
#: Root-relative POSIX paths, never basenames: matching on `path.name` would
#: exempt any nested `commands/git.py` somebody adds later, which is precisely
#: the module most likely to want to format git errors.
SEAMS = frozenset({SEAM, "github.py"})

#: `sys.stderr` is the output stream, not a subprocess result — console.py
#: writes progress there by design (see test_output_conventions.py).
STREAM_HOLDERS = frozenset({"sys"})


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _stderr_reads(tree: ast.Module) -> list[int]:
    """Line numbers of `<something>.stderr` reads that are not `sys.stderr`."""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != "stderr":
            continue
        if isinstance(node.value, ast.Name) and node.value.id in STREAM_HOLDERS:
            continue
        hits.append(node.lineno)
    return hits


def _getattr_stderr_reads(tree: ast.Module) -> list[int]:
    """Line numbers of `getattr(x, "stderr")` calls."""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "getattr"):
            continue
        if any(
            isinstance(a, ast.Constant) and a.value == "stderr" for a in node.args
        ):
            hits.append(node.lineno)
    return hits


def _scan(root: Path, approved: frozenset[str]) -> tuple[list[str], set[str]]:
    """(offending "path:line" strings, approved paths that actually read stderr).

    Takes *root* so the rule itself can be tested against a synthetic tree.
    """
    offenders: list[str] = []
    readers: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        hits = _stderr_reads(tree) + _getattr_stderr_reads(tree)
        if not hits:
            continue
        rel = _rel(path, root)
        if rel in approved:
            readers.add(rel)
            continue
        offenders.extend(f"{rel}:{line}" for line in sorted(hits))
    return offenders, readers


def test_subprocess_stderr_is_read_only_in_the_seams() -> None:
    """Every other module must go through explain_failure/report_failure.

    Reading a subprocess's stderr is how an ad-hoc error format starts: once a
    caller holds the text it will format it its own way, and the next caller
    will format it differently. Covers `getattr(r, "stderr")` too — both seams
    legitimately use it (a CompletedProcess from capture=False has no stderr at
    all), so the escape hatch is real and has to be closed for everyone else.
    """
    offenders, readers = _scan(SRC, SEAMS)

    assert offenders == [], (
        f"subprocess stderr must only be read in {sorted(SEAMS)}; "
        f"found reads in: {offenders}. "
        "Use git.explain_failure() / git.report_failure() instead."
    )
    assert SEAM in readers, (
        f"reinicorn/{SEAM} no longer reads stderr — the seam moved and this "
        "test is now guarding nothing."
    )


def test_a_nested_module_cannot_borrow_a_seam_name(tmp_path: Path) -> None:
    """The rule matches root-relative paths, not basenames.

    Exempting by basename would let a new `commands/git.py` read stderr
    undetected — a hole in the enforcement defeats the enforcement.
    """
    (tmp_path / "commands").mkdir()
    (tmp_path / "git.py").write_text("def f(r):\n    return r.stderr\n")
    (tmp_path / "commands" / "git.py").write_text("def f(r):\n    return r.stderr\n")
    (tmp_path / "commands" / "other.py").write_text(
        'def f(r):\n    return getattr(r, "stderr")\n'
    )

    offenders, readers = _scan(tmp_path, frozenset({"git.py"}))

    assert readers == {"git.py"}
    assert offenders == ["commands/git.py:2", "commands/other.py:2"]


def test_the_seam_exports_what_callers_need() -> None:
    """A rule that leaves callers no alternative gets worked around."""
    from reinicorn import git

    for name in ("GitError", "classify_failure", "classify_result",
                 "explain_failure", "report_failure", "url_protocol"):
        assert hasattr(git, name), f"reinicorn.git.{name} is missing"
