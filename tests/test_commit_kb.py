"""Tests for commit_kb() auto-commit utility."""

from __future__ import annotations

import shutil
from pathlib import Path

from reinicorn.git import run_git
from reinicorn.kb import commit_kb


def test_commit_kb_commits_new_file(kb_clone_repo: Path) -> None:
    (kb_clone_repo / "kb" / "ideas").mkdir(parents=True, exist_ok=True)
    (kb_clone_repo / "kb" / "ideas" / "test.md").write_text("# Test idea\n")

    result = commit_kb(kb_clone_repo, "test: add idea")

    assert result is True
    # Verify commit exists in the kb clone
    log = run_git("log", "--oneline", "-1", cwd=kb_clone_repo / "kb")
    assert "test: add idea" in log.stdout


def test_commit_kb_returns_false_when_nothing_to_commit(
    kb_clone_repo: Path, capsys,
) -> None:
    result = commit_kb(kb_clone_repo, "nothing here")
    assert result is False
    # A genuine no-op must stay silent — only a *failed* commit reports.
    assert capsys.readouterr().out == ""


def test_commit_kb_reports_a_failed_commit(kb_clone_repo: Path, capsys) -> None:
    """Staged work that does not get committed must not look like a no-op.

    Both cases return False; without a message a doc could appear written and
    silently never be saved.
    """
    kb = kb_clone_repo / "kb"
    (kb / "note.md").write_text("# Note\n")
    hook = kb / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho 'refused by test hook' >&2\nexit 1\n")
    hook.chmod(0o755)

    assert commit_kb(kb_clone_repo, "test: should fail") is False
    out = capsys.readouterr().out
    assert "Could not commit the kb" in out
    assert "refused by test hook" in out


def test_commit_kb_fixes_detached_head(kb_clone_repo: Path) -> None:
    """If kb is on detached HEAD, commit_kb should checkout main first."""
    kb = kb_clone_repo / "kb"
    # Detach HEAD
    head = run_git("rev-parse", "HEAD", cwd=kb).stdout.strip()
    run_git("checkout", "-q", head, cwd=kb)

    # Write a file and commit
    (kb / "test.md").write_text("detached test\n")
    result = commit_kb(kb_clone_repo, "fix: from detached")
    assert result is True

    # Should be back on main
    branch = run_git("symbolic-ref", "--short", "HEAD", cwd=kb).stdout.strip()
    assert branch == "main"


def test_commit_kb_paths_leaves_unrelated_changes_uncommitted(
    kb_clone_repo: Path,
) -> None:
    """With paths given, only those files land in the commit; a pre-existing
    dirty file stays modified in the working tree (issue #35)."""
    kb = kb_clone_repo / "kb"
    run_git("commit", "-q", "--allow-empty", "-m", "base", cwd=kb)
    (kb / "README.md").write_text("# Kb\n\nunrelated pre-existing edit\n")

    (kb / "ideas").mkdir()
    idea = kb / "ideas" / "scoped.md"
    idea.write_text("# Scoped idea\n")

    result = commit_kb(kb_clone_repo, "idea: scoped", paths=[idea])

    assert result is True
    shown = run_git(
        "show", "--name-only", "--format=", "HEAD", cwd=kb
    ).stdout.split()
    assert shown == ["ideas/scoped.md"]
    # The unrelated edit is still uncommitted in the working tree.
    status = run_git("status", "--porcelain", cwd=kb).stdout
    assert " M README.md" in status


def test_commit_kb_paths_excludes_already_staged_unrelated_changes(
    kb_clone_repo: Path,
) -> None:
    """An unrelated edit already sitting in the index must not land in the
    scoped commit; it stays staged afterwards (issue #35)."""
    kb = kb_clone_repo / "kb"
    run_git("commit", "-q", "--allow-empty", "-m", "base", cwd=kb)
    (kb / "README.md").write_text("# Kb\n\nunrelated staged edit\n")
    run_git("add", "README.md", cwd=kb)

    (kb / "ideas").mkdir()
    idea = kb / "ideas" / "scoped.md"
    idea.write_text("# Scoped idea\n")

    result = commit_kb(kb_clone_repo, "idea: scoped", paths=[idea])

    assert result is True
    shown = run_git(
        "show", "--name-only", "--format=", "HEAD", cwd=kb
    ).stdout.split()
    assert shown == ["ideas/scoped.md"]
    # The unrelated edit is excluded from the commit and remains staged.
    status = run_git("status", "--porcelain", cwd=kb).stdout
    assert "M  README.md" in status


def test_commit_kb_paths_returns_false_when_paths_unchanged(
    kb_clone_repo: Path,
) -> None:
    """Dirt elsewhere in the tree must not trigger a commit when the given
    paths have no changes."""
    kb = kb_clone_repo / "kb"
    (kb / "README.md").write_text("# Kb\n\nunrelated edit\n")

    result = commit_kb(
        kb_clone_repo, "idea: nothing", paths=[kb / "ideas" / "absent.md"]
    )

    assert result is False
    status = run_git("status", "--porcelain", cwd=kb).stdout
    assert " M README.md" in status


def test_commit_kb_paths_stages_deletions_for_moves(
    kb_clone_repo: Path,
) -> None:
    """A directory move (plan complete) commits both the deletion and the
    addition when both dirs are passed as paths."""
    kb = kb_clone_repo / "kb"
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
        kb_clone_repo, "plan: complete my-plan", paths=[active, completed]
    )

    assert result is True
    # --no-renames so the move shows as an explicit delete + add pair.
    shown = run_git(
        "show", "--name-status", "--no-renames", "--format=", "HEAD", cwd=kb
    ).stdout.split()
    assert shown == ["D", "active/my-plan/plan.md", "A", "completed/my-plan/plan.md"]
    status = run_git("status", "--porcelain", cwd=kb).stdout
    assert " M README.md" in status


def test_commit_kb_stages_nothing_in_parent(kb_clone_repo: Path) -> None:
    """After commit_kb, the parent repo must have nothing staged.

    This is a regression tripwire — after stage_kb_pointer is deleted,
    commit_kb must not stage kb pointer changes in the parent.
    """
    kb = kb_clone_repo / "kb"
    (kb / "note.md").write_text("hi\n")
    assert commit_kb(kb_clone_repo, "doc: note") is True
    r = run_git("diff", "--cached", "--name-only", cwd=kb_clone_repo)
    assert r.stdout.strip() == ""
