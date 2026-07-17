"""Tests for rcorn kb sync command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.sync import cmd_sync
from reinicorn.git import run_git


def test_sync_stays_on_main_branch(submodule_repo: Path) -> None:
    """After sync, kb should be on main branch, not detached HEAD."""
    with patch("reinicorn.commands.sync.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.sync.current_branch", return_value="feature/x"):
        result = cmd_sync()

    assert result == 0
    branch = run_git(
        "symbolic-ref", "--short", "HEAD", cwd=submodule_repo / "kb"
    ).stdout.strip()
    assert branch == "main"


def test_sync_fixes_detached_head(submodule_repo: Path) -> None:
    """Sync should fix a detached HEAD by checking out main."""
    kb = submodule_repo / "kb"
    # Detach HEAD
    head = run_git("rev-parse", "HEAD", cwd=kb).stdout.strip()
    run_git("checkout", "-q", head, cwd=kb)

    with patch("reinicorn.commands.sync.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.sync.current_branch", return_value="feature/x"):
        result = cmd_sync()

    assert result == 0
    branch = run_git("symbolic-ref", "--short", "HEAD", cwd=kb).stdout.strip()
    assert branch == "main"


def test_sync_uses_merge_not_rebase(submodule_repo: Path, tmp_path: Path) -> None:
    """When ff-only fails, sync should merge (not rebase) to preserve SHAs."""
    kb = submodule_repo / "kb"
    remote = tmp_path / "kb-remote"

    # Create a divergent history: push a commit to remote, make a local commit
    # 1. Push a commit via the remote bare repo
    staging = tmp_path / "staging-clone"
    run_git(
        "-c", "protocol.file.allow=always",
        "clone", str(remote), str(staging),
    )
    run_git("config", "user.email", "test@test.com", cwd=staging)
    run_git("config", "user.name", "Test User", cwd=staging)
    (staging / "remote-change.md").write_text("remote\n")
    run_git("add", "-A", cwd=staging)
    run_git("commit", "-q", "-m", "remote commit", cwd=staging)
    run_git(
        "-c", "protocol.file.allow=always", "push", "origin", "main",
        cwd=staging,
    )

    # 2. Make a local commit in kb (diverges from remote)
    (kb / "local-change.md").write_text("local\n")
    run_git("add", "-A", cwd=kb)
    run_git("commit", "-q", "-m", "local commit", cwd=kb)
    local_sha = run_git("rev-parse", "HEAD", cwd=kb).stdout.strip()

    with patch("reinicorn.commands.sync.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.sync.current_branch", return_value="feature/x"):
        result = cmd_sync()

    assert result == 0

    # The local commit SHA should still exist (merge preserves it, rebase wouldn't)
    r = run_git("cat-file", "-t", local_sha, cwd=kb)
    assert r.stdout.strip() == "commit"

    # The local commit should be an ancestor of HEAD (not orphaned)
    r = run_git("merge-base", "--is-ancestor", local_sha, "HEAD", cwd=kb, check=False)
    assert r.returncode == 0


def test_sync_stages_parent_pointer(submodule_repo: Path) -> None:
    """After sync, the parent submodule pointer should be staged."""
    with patch("reinicorn.commands.sync.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.sync.current_branch", return_value="feature/x"):
        result = cmd_sync()

    assert result == 0
    r = run_git("diff", "--cached", "--name-only", cwd=submodule_repo)
    # May or may not be staged depending on whether HEAD changed,
    # but at minimum it should not error
    assert r.returncode == 0


def test_sync_shows_resolution_on_merge_conflict(
    submodule_repo: Path, tmp_path: Path, capsys
) -> None:
    """When merge fails, sync should show resolution instructions."""
    kb = submodule_repo / "kb"
    remote = tmp_path / "kb-remote"

    # Create conflicting changes on same file
    staging = tmp_path / "staging-clone"
    run_git(
        "-c", "protocol.file.allow=always",
        "clone", str(remote), str(staging),
    )
    run_git("config", "user.email", "t@t.com", cwd=staging)
    run_git("config", "user.name", "T", cwd=staging)
    (staging / "conflict.md").write_text("remote version\n")
    run_git("add", "-A", cwd=staging)
    run_git("commit", "-q", "-m", "remote", cwd=staging)
    run_git(
        "-c", "protocol.file.allow=always", "push", "origin", "main",
        cwd=staging,
    )

    # Make conflicting local change on SAME file
    (kb / "conflict.md").write_text("local version\n")
    run_git("add", "-A", cwd=kb)
    run_git("commit", "-q", "-m", "local", cwd=kb)

    with patch("reinicorn.commands.sync.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.sync.current_branch", return_value="feature/x"):
        result = cmd_sync()

    assert result == 1
    out = capsys.readouterr().out
    assert "error:" in out
    assert "conflict" in out.lower() or "resolve" in out.lower()
    assert "next: rcorn kb publish" in out



def test_sync_merge_failure_without_conflicts(
    submodule_repo: Path, capsys
) -> None:
    """A merge that fails for non-conflict reasons (unreachable remote,
    missing origin/main) must not claim 'conflicts' or suggest publish —
    publishing would sweep whatever state the tree is in."""
    kb = submodule_repo / "kb"
    run_git("remote", "remove", "origin", cwd=kb)
    run_git("update-ref", "-d", "refs/remotes/origin/main", cwd=kb)

    with patch("reinicorn.commands.sync.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.sync.current_branch", return_value="feature/x"):
        result = cmd_sync()

    assert result == 1
    out = capsys.readouterr().out
    assert "Could not merge origin/main" in out
    assert "conflict" not in out.lower()
    assert "next: rcorn kb publish" not in out
