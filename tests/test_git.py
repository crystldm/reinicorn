"""Tests for reinicorn.git."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from reinicorn.git import (
    current_branch,
    reinicorn_root,
    repo_root,
    repo_slug,
    run_git,
    sanitize_branch,
)


def test_repo_root_returns_path(kb_repo: Path):
    def _fake_git(*args, **kwargs):
        if "--show-superproject-working-tree" in args:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="\n")
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=str(kb_repo) + "\n"
        )
    with patch("reinicorn.git.run_git", side_effect=_fake_git):
        result = repo_root()
        assert result == kb_repo


def test_repo_root_walks_up_from_submodule(tmp_path: Path):
    """repo_root() returns superproject root when called from inside a submodule."""
    parent = tmp_path / "parent-project"
    submod = tmp_path / "parent-project" / "kb"

    def _fake_git(*args, **kwargs):
        if "--show-superproject-working-tree" in args:
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout=str(parent) + "\n"
            )
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=str(submod) + "\n"
        )
    with patch("reinicorn.git.run_git", side_effect=_fake_git):
        result = repo_root()
        assert result == parent


def test_repo_root_when_superproject_check_fails(tmp_path: Path):
    """repo_root() still works if --show-superproject-working-tree fails (old git)."""
    def _fake_git(*args, **kwargs):
        if "--show-superproject-working-tree" in args:
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=str(tmp_path) + "\n"
        )
    with patch("reinicorn.git.run_git", side_effect=_fake_git):
        result = repo_root()
        assert result == tmp_path


def test_repo_root_returns_none_outside_repo():
    with patch("reinicorn.git.run_git", side_effect=subprocess.CalledProcessError(1, "git")):
        result = repo_root(quiet=True)
        assert result is None


def test_current_branch_returns_name(kb_repo: Path):
    run_git("checkout", "-b", "feature/test", cwd=kb_repo)
    with patch("reinicorn.git.run_git") as mock:
        mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="feature/test\n"
        )
        assert current_branch() == "feature/test"


def test_current_branch_detached_returns_empty():
    with patch("reinicorn.git.run_git", side_effect=subprocess.CalledProcessError(1, "git")):
        assert current_branch() == ""


def test_reinicorn_root():
    root = reinicorn_root()
    # Should be the repo root containing src/
    assert (root / "src" / "reinicorn" / "__init__.py").is_file()


def test_run_git_success(kb_repo: Path):
    r = run_git("rev-parse", "--show-toplevel", cwd=kb_repo)
    assert r.returncode == 0
    assert kb_repo.name in r.stdout


def test_run_git_ignores_inherited_git_env(kb_repo: Path, monkeypatch: pytest.MonkeyPatch):
    """run_git(cwd=X) must rediscover the repo from X, not honor inherited GIT_DIR.

    Reproduces the worktree-hook bug: git invokes hooks with GIT_DIR pointing
    at the parent worktree's gitdir. If run_git inherits that env, every
    `cwd=submodule_dir` call silently targets the parent gitdir instead.
    """
    monkeypatch.setenv("GIT_DIR", "/nonexistent-gitdir")
    monkeypatch.setenv("GIT_WORK_TREE", "/nonexistent-worktree")
    monkeypatch.setenv("GIT_INDEX_FILE", "/nonexistent-index")
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", "/nonexistent-objects")
    monkeypatch.setenv("GIT_COMMON_DIR", "/nonexistent-common")

    r = run_git("rev-parse", "--show-toplevel", cwd=kb_repo)
    assert r.returncode == 0
    assert Path(r.stdout.strip()) == kb_repo.resolve()


# --- sanitize_branch tests ---


def test_sanitize_branch_replaces_slashes():
    assert sanitize_branch("feature/mvp") == "feature-mvp"


def test_sanitize_branch_multiple_slashes():
    assert sanitize_branch("feature/mvp/sub") == "feature-mvp-sub"


def test_sanitize_branch_no_slash():
    assert sanitize_branch("main") == "main"


def test_sanitize_branch_idempotent():
    assert sanitize_branch("feature-mvp") == "feature-mvp"


def test_sanitize_branch_collapses_traversal_names():
    assert sanitize_branch("..") == "-"
    assert sanitize_branch(".") == "-"
    assert sanitize_branch("") == "-"


def test_sanitize_branch_replaces_backslashes():
    assert sanitize_branch("..\\evil") == "..-evil"


# --- repo_slug tests ---


def test_repo_slug_from_ssh_url():
    with patch("reinicorn.git.repo_root", return_value=Path("/fake")), \
         patch("reinicorn.git.run_git") as mock:
        mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="git@github.com:acme/reins.git\n"
        )
        assert repo_slug() == "reins"


def test_repo_slug_from_https_url():
    with patch("reinicorn.git.repo_root", return_value=Path("/fake")), \
         patch("reinicorn.git.run_git") as mock:
        mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://github.com/acme/reins.git\n"
        )
        assert repo_slug() == "reins"


def test_repo_slug_strips_trailing_git():
    with patch("reinicorn.git.repo_root", return_value=Path("/fake")), \
         patch("reinicorn.git.run_git") as mock:
        mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="git@github.com:acme/my-project.git\n"
        )
        assert repo_slug() == "my-project"


def test_repo_slug_no_git_suffix():
    with patch("reinicorn.git.repo_root", return_value=Path("/fake")), \
         patch("reinicorn.git.run_git") as mock:
        mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://github.com/acme/foo\n"
        )
        assert repo_slug() == "foo"


def test_repo_slug_fallback_on_error():
    with patch("reinicorn.git.repo_root", return_value=None), \
         patch("reinicorn.git.run_git", side_effect=Exception("no remote")):
        assert repo_slug() == "unknown"
