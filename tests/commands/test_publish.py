"""Tests for rcorn kb publish command."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.publish import cmd_publish
from reinicorn.git import run_git


def test_publish_pushes_to_remote(submodule_repo: Path, tmp_path: Path) -> None:
    """Publish should push kb commits to the remote."""
    kb = submodule_repo / "kb"
    (kb / "new-file.md").write_text("# New\n")
    run_git("add", "-A", cwd=kb)
    run_git("commit", "-q", "-m", "test commit", cwd=kb)

    with patch("reinicorn.commands.publish.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.publish.can_publish", return_value=True):
        result = cmd_publish()

    assert result == 0

    # Verify the remote received the push
    remote = tmp_path / "kb-remote"
    log = run_git("log", "--oneline", "-1", cwd=remote).stdout
    assert "test commit" in log


def test_publish_stays_on_main(submodule_repo: Path) -> None:
    """Publish should ensure kb is on main, not detached."""
    kb = submodule_repo / "kb"
    # Detach HEAD
    head = run_git("rev-parse", "HEAD", cwd=kb).stdout.strip()
    run_git("checkout", "-q", head, cwd=kb)

    with patch("reinicorn.commands.publish.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.publish.can_publish", return_value=True):
        result = cmd_publish()

    assert result == 0
    branch = run_git("symbolic-ref", "--short", "HEAD", cwd=kb).stdout.strip()
    assert branch == "main"


def test_publish_updates_parent_pointer(submodule_repo: Path) -> None:
    """After publish, parent submodule pointer should be staged or committed."""
    kb = submodule_repo / "kb"
    (kb / "new-file.md").write_text("# New\n")
    run_git("add", "-A", cwd=kb)
    run_git("commit", "-q", "-m", "test commit", cwd=kb)

    with patch("reinicorn.commands.publish.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.publish.can_publish", return_value=True):
        result = cmd_publish()

    assert result == 0

    # Parent should have kb pointer staged
    staged = run_git("diff", "--cached", "--name-only", cwd=submodule_repo).stdout
    assert "kb" in staged


def test_publish_shows_resolution_steps_on_retry_failure(
    submodule_repo: Path, capsys
) -> None:
    """When retry also fails, publish shows step-by-step resolution instructions."""
    with patch("reinicorn.commands.publish.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.publish.can_publish", return_value=True), \
         patch("reinicorn.commands.publish.push_main_with_retry") as mock_push:
        mock_push.return_value = subprocess.CompletedProcess([], 1, "", "rejected")
        result = cmd_publish()

    assert result == 1
    out = capsys.readouterr()
    assert "error:" in out.out
    # Publish already pulled before the retry; after resolving conflicts,
    # publish alone auto-commits and pushes — no sync step needed.
    assert "next: rcorn kb publish" in out.out
    assert "rcorn kb sync" not in out.out + out.err


def test_publish_blocked_in_incognito(kb_repo: Path, capsys) -> None:
    """Publish should refuse when in incognito mode."""
    with patch("reinicorn.commands.publish.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.publish.can_publish", return_value=False), \
         patch("reinicorn.commands.publish.get_mode", return_value="incognito"):
        result = cmd_publish()

    assert result == 1
    out = capsys.readouterr().out
    assert "error:" in out
    assert "incognito" in out.lower()


def test_publish_blocked_suggests_mode_enable(kb_repo: Path, capsys) -> None:
    """Blocked publish must suggest the command that actually unblocks it."""
    for mode in ("incognito", "disabled"):
        with patch("reinicorn.commands.publish.repo_root", return_value=kb_repo), \
             patch("reinicorn.commands.publish.can_publish", return_value=False), \
             patch("reinicorn.commands.publish.get_mode", return_value=mode):
            result = cmd_publish()
        assert result == 1
        out = capsys.readouterr().out
        assert "next: rcorn mode enable" in out
        assert "rcorn mode incognito" not in out


def test_publish_retries_after_diverged_history(
    submodule_repo: Path, tmp_path: Path
) -> None:
    """Publish should auto-retry after pull when remote has diverged."""
    kb = submodule_repo / "kb"
    remote = tmp_path / "kb-remote"

    # Push a divergent commit to remote
    staging = tmp_path / "staging-clone"
    run_git(
        "-c", "protocol.file.allow=always",
        "clone", str(remote), str(staging),
    )
    run_git("config", "user.email", "t@t.com", cwd=staging)
    run_git("config", "user.name", "T", cwd=staging)
    (staging / "remote.md").write_text("remote\n")
    run_git("add", "-A", cwd=staging)
    run_git("commit", "-q", "-m", "remote", cwd=staging)
    run_git(
        "-c", "protocol.file.allow=always", "push", "origin", "main",
        cwd=staging,
    )

    # Make local commit
    (kb / "local.md").write_text("local\n")
    run_git("add", "-A", cwd=kb)
    run_git("commit", "-q", "-m", "local", cwd=kb)

    with patch("reinicorn.commands.publish.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.publish.can_publish", return_value=True):
        result = cmd_publish()

    assert result == 0

