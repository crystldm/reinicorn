"""Tests for reins kb git command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from reinicorn.commands.kb_git import cmd_kb_git


def test_kb_git_runs_command_in_kb(submodule_repo: Path, capsys) -> None:
    """kb-git should run git commands inside the kb directory."""
    with patch("reinicorn.commands.kb_git.repo_root", return_value=submodule_repo):
        result = cmd_kb_git(["status"])

    assert result == 0


def test_kb_git_passes_args(submodule_repo: Path) -> None:
    """kb-git should pass all arguments to git."""
    with patch("reinicorn.commands.kb_git.repo_root", return_value=submodule_repo):
        result = cmd_kb_git(["log", "--oneline", "-1"])

    assert result == 0


def test_kb_git_returns_git_exit_code(submodule_repo: Path) -> None:
    """kb-git should forward git's exit code."""
    with patch("reinicorn.commands.kb_git.repo_root", return_value=submodule_repo):
        result = cmd_kb_git(["log", "--oneline", "nonexistent-ref"])

    assert result != 0


def test_kb_git_ignores_inherited_git_env(
    submodule_repo: Path, monkeypatch: pytest.MonkeyPatch, capfd
) -> None:
    """kb git must rediscover the kb repo from cwd, not honor inherited GIT_DIR.

    Same worktree-hook bug as issue #25: git invokes hooks with GIT_DIR pointing
    at the parent worktree's gitdir. If kb git inherits that env, the git command
    targets the parent gitdir instead of the kb submodule. With a nonexistent
    GIT_DIR a leaked env makes git exit 128; a stripped env rediscovers from the
    kb cwd and exits 0.
    """
    monkeypatch.setenv("GIT_DIR", "/nonexistent-gitdir")
    monkeypatch.setenv("GIT_WORK_TREE", "/nonexistent-worktree")
    monkeypatch.setenv("GIT_INDEX_FILE", "/nonexistent-index")
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", "/nonexistent-objects")
    monkeypatch.setenv("GIT_COMMON_DIR", "/nonexistent-common")

    with patch("reinicorn.commands.kb_git.repo_root", return_value=submodule_repo):
        result = cmd_kb_git(["rev-parse", "--show-toplevel"])

    assert result == 0


def test_kb_git_no_args_shows_usage(kb_repo: Path, capsys) -> None:
    """kb-git with no args should show usage hint."""
    with patch("reinicorn.commands.kb_git.repo_root", return_value=kb_repo):
        result = cmd_kb_git([])

    assert result == 1
    assert "Usage" in capsys.readouterr().out
