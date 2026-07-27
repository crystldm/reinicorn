"""Tests for how `rcorn hooks install` reports a failed repo lookup.

`run_git(check=True)` raises GitError on *any* nonzero exit, so catching it and
printing "Not inside a git repository" turned permission errors, a corrupt
repository, and a broken git config into the same wrong sentence with git's
own explanation thrown away.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.hooks_install import cmd_hooks_install
from reinicorn.git import GitError


def test_outside_a_repo_says_so(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cmd_hooks_install() == 1
    out = capsys.readouterr().out
    assert "Not inside a git repository" in out


def test_other_git_failures_are_not_called_not_a_repository(
    tmp_path: Path, monkeypatch, capsys,
):
    """A permission error is not a missing repository."""
    monkeypatch.chdir(tmp_path)
    boom = GitError(
        128, ["git", "rev-parse", "--git-common-dir"], "",
        "fatal: detected dubious ownership in repository at '/srv/repo'\n",
    )
    with patch("reinicorn.commands.hooks_install.run_git", side_effect=boom):
        assert cmd_hooks_install() == 1
    out = capsys.readouterr().out
    assert "Not inside a git repository" not in out
    assert "dubious ownership" in out


def test_missing_git_binary_is_reported_as_such(
    tmp_path: Path, monkeypatch, capsys,
):
    monkeypatch.chdir(tmp_path)
    with patch(
        "reinicorn.commands.hooks_install.run_git",
        side_effect=FileNotFoundError("git"),
    ):
        assert cmd_hooks_install() == 1
    out = capsys.readouterr().out
    assert "git" in out.lower()
    assert "Not inside a git repository" not in out
