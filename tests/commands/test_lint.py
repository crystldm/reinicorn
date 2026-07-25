"""Tests for `rcorn kb lint`.

This module had zero coverage until these tests existed. `commands/lint.py`
is reachable only through `cli._DISPATCH[("kb", "lint")]`, which lazy-imports
it via `importlib.import_module` — so with nothing dispatching `kb lint`, the
module was never even imported during the suite.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from reinicorn.cli import main
from reinicorn.commands.lint import cmd_lint


def test_lint_returns_one_outside_repo():
    with patch("reinicorn.commands.lint.repo_root", return_value=None):
        assert cmd_lint() == 1


def test_lint_runs_rules_and_reports(kb_repo: Path, capsys):
    with patch("reinicorn.commands.lint.repo_root", return_value=kb_repo):
        assert cmd_lint() == 0
    assert "Lint Summary" in capsys.readouterr().out


def test_lint_exits_when_no_kb_submodule(tmp_path: Path):
    """require_kb_dir raises SystemExit(1) rather than returning a code."""
    with (
        patch("reinicorn.commands.lint.repo_root", return_value=tmp_path),
        pytest.raises(SystemExit) as exc,
    ):
        cmd_lint()
    assert exc.value.code == 1


def test_lint_propagates_error_severity_failure(kb_repo: Path):
    with (
        patch("reinicorn.commands.lint.repo_root", return_value=kb_repo),
        patch("reinicorn.commands.lint.run_lints", return_value=1) as run,
    ):
        assert cmd_lint() == 1
    run.assert_called_once_with(kb_repo)


def test_kb_lint_dispatch_entry_resolves(kb_repo: Path):
    """The lazy `_load("lint", "cmd_lint")` entry actually imports and runs."""
    with (
        patch("reinicorn.commands.lint.repo_root", return_value=kb_repo),
        patch("reinicorn.commands.lint.run_lints", return_value=0) as run,
    ):
        assert main(["kb", "lint"]) == 0
    run.assert_called_once_with(kb_repo)
