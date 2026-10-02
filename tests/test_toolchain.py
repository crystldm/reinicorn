"""Golden principle 17 — no tool sprawl: uv is the sole Python toolchain.

Sweeps every workflow YAML this repo owns — its own CI and the templates
`rcorn review setup` installs into kb repos — for a second Python toolchain
(pip, setup-python, venv, pipx) on non-comment lines.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from reinicorn.git import reinicorn_root

_PRINCIPLE = "kb/reinicorn/golden-principles.md#17"

# Each pattern names one way a second toolchain sneaks in. `uv pip ...` is
# uv's own pip-compatible interface and is not a second toolchain.
_BANNED = {
    "pip install": re.compile(r"(?<!uv )\bpip3? install\b"),
    "python -m pip": re.compile(r"python3? -m pip\b"),
    "python -m venv": re.compile(r"python3? -m venv\b"),
    "pipx": re.compile(r"\bpipx\b"),
    "actions/setup-python": re.compile(r"actions/setup-python"),
}


def _workflow_files() -> list[Path]:
    root = reinicorn_root()
    files = sorted(root.glob(".github/workflows/*.yml")) + sorted(root.glob("workflows/*.yml"))
    assert files, "no workflow YAML found — the sweep would be vacuous"
    return files


def _rel(path: Path) -> str:
    return str(path.relative_to(reinicorn_root()))


@pytest.mark.parametrize("path", _workflow_files(), ids=_rel)
def test_workflows_use_only_uv(path: Path):
    violations = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        for name, pattern in _BANNED.items():
            if pattern.search(line):
                violations.append(f"{path.name}:{lineno} — {name}: {line.strip()}")
    assert not violations, (
        "second Python toolchain in a workflow (uv is the only one — "
        f"use astral-sh/setup-uv + `uv run`; see {_PRINCIPLE}):\n  "
        + "\n  ".join(violations)
    )


def test_workflows_that_run_python_set_up_uv():
    """Any workflow that invokes uv must install it first, so the rule can't
    be satisfied by a workflow that merely assumes uv is on the runner."""
    for path in _workflow_files():
        code = "\n".join(
            ln for ln in path.read_text().splitlines() if not ln.lstrip().startswith("#")
        )
        if re.search(r"\buv (run|tool|sync|pip)\b", code):
            assert "astral-sh/setup-uv@" in code, (
                f"{path.name} runs uv without astral-sh/setup-uv (see {_PRINCIPLE})"
            )
