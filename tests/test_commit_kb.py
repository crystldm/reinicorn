"""Tests for commit_kb() auto-commit utility."""

from __future__ import annotations

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
    submodule_repo: Path,
) -> None:
    result = commit_kb(submodule_repo, "nothing here")
    assert result is False


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
