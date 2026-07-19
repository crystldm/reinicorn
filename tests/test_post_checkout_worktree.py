"""Tests for worktree-aware kb init (--reference) and hook install destination.

Spec: kb/reinicorn/specs/worktree-aware-kb-resolution.md
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.internal.post_checkout import _kb_reference_args
from reinicorn.git import run_git


def _add_worktree(parent: Path, name: str) -> Path:
    wt = parent.parent / name
    run_git("worktree", "add", "-q", str(wt), "-b", name, cwd=parent)
    return wt


def test_kb_reference_args_without_shared_module(tmp_path: Path):
    """No <common>/modules/kb (fresh clone) → plain init, no extra args."""
    repo = tmp_path / "plain"
    repo.mkdir()
    run_git("init", "-q", str(repo))
    assert _kb_reference_args(repo) == []


def test_kb_reference_args_ignores_broken_module(tmp_path: Path):
    """A module dir without objects/ must fall back to plain init."""
    repo = tmp_path / "broken"
    repo.mkdir()
    run_git("init", "-q", str(repo))
    (repo / ".git" / "modules" / "kb").mkdir(parents=True)
    assert _kb_reference_args(repo) == []


def test_kb_reference_args_at_main_checkout_root(submodule_repo: Path):
    """Relative --git-common-dir output (.git) joins correctly against root."""
    expected = (submodule_repo / ".git" / "modules" / "kb").resolve()
    assert _kb_reference_args(submodule_repo) == ["--reference", str(expected)]


def test_kb_reference_args_in_worktree(submodule_repo: Path):
    """A linked worktree borrows from the main checkout's module clone."""
    wt = _add_worktree(submodule_repo, "wt-ref")
    expected = (submodule_repo / ".git" / "modules" / "kb").resolve()
    assert _kb_reference_args(wt) == ["--reference", str(expected)]


def test_post_checkout_inits_worktree_kb_with_reference(
    submodule_repo: Path, monkeypatch,
):
    """cmd_post_checkout in a fresh worktree initializes kb via alternates."""
    from reinicorn.commands.internal.post_checkout import cmd_post_checkout

    # git 2.38+ blocks local file transport; worktrees share the repo config
    run_git("config", "protocol.file.allow", "always", cwd=submodule_repo)
    wt = _add_worktree(submodule_repo, "wt-init")
    assert not (wt / "kb" / ".git").exists()

    monkeypatch.chdir(wt)
    with patch(
        "reinicorn.commands.internal.post_checkout.hook_check", return_value=True,
    ):
        assert cmd_post_checkout(["", "", "1"]) == 0

    assert (wt / "kb" / ".git").exists()
    alternates = (
        submodule_repo / ".git" / "worktrees" / "wt-init" / "modules" / "kb"
        / "objects" / "info" / "alternates"
    )
    assert alternates.is_file(), "kb clone should borrow objects via --reference"
    assert "modules/kb/objects" in alternates.read_text()


def test_hooks_install_targets_common_dir(tmp_path: Path, monkeypatch):
    """hooks install from a worktree lands git hooks in the shared hooks dir."""
    from reinicorn.commands.hooks_install import cmd_hooks_install

    repo = tmp_path / "hookrepo"
    repo.mkdir()
    run_git("init", "-q", "-b", "main", str(repo))
    run_git("config", "user.email", "test@test.com", cwd=repo)
    run_git("config", "user.name", "Test User", cwd=repo)
    run_git("commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
    wt = _add_worktree(repo, "hookrepo-wt")

    monkeypatch.chdir(wt)
    assert cmd_hooks_install() == 0

    assert (repo / ".git" / "hooks" / "post-checkout").is_file()
    assert not (repo / ".git" / "worktrees" / "hookrepo-wt" / "hooks").exists()
