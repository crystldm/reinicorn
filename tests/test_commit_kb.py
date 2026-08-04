"""Tests for commit_kb() auto-commit utility."""

from __future__ import annotations

import shutil
from pathlib import Path

from reinicorn.git import run_git
from reinicorn.kb import commit_kb


def test_commit_kb_commits_new_file(submodule_repo: Path) -> None:
    (submodule_repo / "kb" / "ideas").mkdir(parents=True, exist_ok=True)
    (submodule_repo / "kb" / "ideas" / "test.md").write_text("# Test idea\n")

    result = commit_kb(submodule_repo, "test: add idea")

    assert result is True
    # Verify commit exists in submodule
    log = run_git("log", "--oneline", "-1", cwd=submodule_repo / "kb")
    assert "test: add idea" in log.stdout


def test_commit_kb_returns_false_when_nothing_to_commit(
    submodule_repo: Path, capsys,
) -> None:
    result = commit_kb(submodule_repo, "nothing here")
    assert result is False
    # A genuine no-op must stay silent — only a *failed* commit reports.
    assert capsys.readouterr().out == ""


def test_commit_kb_reports_a_failed_commit(submodule_repo: Path, capsys) -> None:
    """Staged work that does not get committed must not look like a no-op.

    Both cases return False; without a message a doc could appear written and
    silently never be saved.
    """
    kb = submodule_repo / "kb"
    (kb / "note.md").write_text("# Note\n")
    hook = kb / ".git" / "hooks" / "pre-commit"
    if not hook.parent.is_dir():  # submodule gitdir lives under .git/modules
        hook = submodule_repo / ".git" / "modules" / "kb" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho 'refused by test hook' >&2\nexit 1\n")
    hook.chmod(0o755)

    assert commit_kb(submodule_repo, "test: should fail") is False
    out = capsys.readouterr().out
    assert "Could not commit the kb" in out
    assert "refused by test hook" in out


def test_commit_kb_fixes_detached_head(submodule_repo: Path) -> None:
    """If kb is on detached HEAD, commit_kb should checkout main first."""
    kb = submodule_repo / "kb"
    # Detach HEAD
    head = run_git("rev-parse", "HEAD", cwd=kb).stdout.strip()
    run_git("checkout", "-q", head, cwd=kb)

    # Write a file and commit
    (kb / "test.md").write_text("detached test\n")
    result = commit_kb(submodule_repo, "fix: from detached")
    assert result is True

    # Should be back on main
    branch = run_git("symbolic-ref", "--short", "HEAD", cwd=kb).stdout.strip()
    assert branch == "main"


def test_commit_kb_stages_parent_pointer(submodule_repo: Path) -> None:
    """After committing in kb, the parent pointer should be staged."""
    (submodule_repo / "kb" / "test.md").write_text("staged pointer test\n")

    commit_kb(submodule_repo, "test: staged pointer")

    # Parent should have kb staged (not committed, just in index)
    r = run_git("diff", "--cached", "--name-only", cwd=submodule_repo)
    assert "kb" in r.stdout


def test_commit_kb_paths_leaves_unrelated_changes_uncommitted(
    submodule_repo: Path,
) -> None:
    """With paths given, only those files land in the commit; a pre-existing
    dirty file stays modified in the working tree (issue #35)."""
    kb = submodule_repo / "kb"
    run_git("commit", "-q", "--allow-empty", "-m", "base", cwd=kb)
    (kb / "README.md").write_text("# Kb\n\nunrelated pre-existing edit\n")

    (kb / "ideas").mkdir()
    idea = kb / "ideas" / "scoped.md"
    idea.write_text("# Scoped idea\n")

    result = commit_kb(submodule_repo, "idea: scoped", paths=[idea])

    assert result is True
    shown = run_git(
        "show", "--name-only", "--format=", "HEAD", cwd=kb
    ).stdout.split()
    assert shown == ["ideas/scoped.md"]
    # The unrelated edit is still uncommitted in the working tree.
    status = run_git("status", "--porcelain", cwd=kb).stdout
    assert " M README.md" in status


def test_commit_kb_paths_returns_false_when_paths_unchanged(
    submodule_repo: Path,
) -> None:
    """Dirt elsewhere in the tree must not trigger a commit when the given
    paths have no changes."""
    kb = submodule_repo / "kb"
    (kb / "README.md").write_text("# Kb\n\nunrelated edit\n")

    result = commit_kb(
        submodule_repo, "idea: nothing", paths=[kb / "ideas" / "absent.md"]
    )

    assert result is False
    status = run_git("status", "--porcelain", cwd=kb).stdout
    assert " M README.md" in status


def test_commit_kb_paths_stages_deletions_for_moves(
    submodule_repo: Path,
) -> None:
    """A directory move (plan complete) commits both the deletion and the
    addition when both dirs are passed as paths."""
    kb = submodule_repo / "kb"
    active = kb / "active" / "my-plan"
    active.mkdir(parents=True)
    (active / "plan.md").write_text("# Plan\n")
    run_git("add", "-A", cwd=kb)
    run_git("commit", "-q", "-m", "seed plan", cwd=kb)
    (kb / "README.md").write_text("# Kb\n\nunrelated edit\n")

    completed = kb / "completed" / "my-plan"
    completed.parent.mkdir(parents=True)
    shutil.move(str(active), str(completed))

    result = commit_kb(
        submodule_repo, "plan: complete my-plan", paths=[active, completed]
    )

    assert result is True
    # --no-renames so the move shows as an explicit delete + add pair.
    shown = run_git(
        "show", "--name-status", "--no-renames", "--format=", "HEAD", cwd=kb
    ).stdout.split()
    assert shown == ["D", "active/my-plan/plan.md", "A", "completed/my-plan/plan.md"]
    status = run_git("status", "--porcelain", cwd=kb).stdout
    assert " M README.md" in status
