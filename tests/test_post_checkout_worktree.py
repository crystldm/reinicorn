"""Tests for worktree-aware kb init (--reference) and hook install destination.

Spec: kb/reinicorn/specs/worktree-aware-kb-resolution.md
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.internal.post_checkout import _clone_reference_args
from reinicorn.git import run_git


def _add_worktree(parent: Path, name: str) -> Path:
    wt = parent.parent / name
    run_git("worktree", "add", "-q", str(wt), "-b", name, cwd=parent)
    return wt


def test_clone_reference_args_without_main_checkout_kb(tmp_path: Path):
    """No kb/ at the main checkout root (fresh clone) → plain clone, no extra args."""
    repo = tmp_path / "plain"
    repo.mkdir()
    run_git("init", "-q", str(repo))
    assert _clone_reference_args(repo) == []


def test_clone_reference_args_ignores_non_git_kb_dir(tmp_path: Path):
    """A kb/ directory without .git (stale leftover) must not be borrowed from."""
    repo = tmp_path / "stale"
    repo.mkdir()
    run_git("init", "-q", str(repo))
    (repo / "kb").mkdir()
    assert _clone_reference_args(repo) == []


def test_clone_reference_args_in_worktree(kb_clone_repo: Path):
    """A linked worktree borrows objects from the main checkout's kb clone."""
    wt = _add_worktree(kb_clone_repo, "wt-ref")
    expected = kb_clone_repo / "kb"
    assert _clone_reference_args(wt) == [
        "--reference-if-able", str(expected), "--dissociate",
    ]


def test_post_checkout_inits_worktree_kb_with_reference(
    kb_clone_repo: Path, monkeypatch,
):
    """cmd_post_checkout in a fresh worktree clones kb, borrowing objects from
    the main checkout's kb via --reference-if-able/--dissociate."""
    from reinicorn.commands.internal.post_checkout import cmd_post_checkout

    wt = _add_worktree(kb_clone_repo, "wt-init")
    assert not (wt / "kb" / ".git").exists()

    monkeypatch.chdir(wt)
    with patch(
        "reinicorn.commands.internal.post_checkout.hook_check", return_value=True,
    ), patch(
        "reinicorn.commands.internal.post_checkout.run_git", wraps=run_git,
    ) as spy:
        assert cmd_post_checkout(["", "", "1"]) == 0

    assert (wt / "kb" / ".git").exists()
    clone_call = next(c for c in spy.call_args_list if "clone" in c.args)
    assert "--reference-if-able" in clone_call.args
    assert str(kb_clone_repo / "kb") in clone_call.args
    assert "--dissociate" in clone_call.args


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
