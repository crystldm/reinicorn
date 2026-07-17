"""Tests for reins _post-merge hook — plan archival."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.internal.post_merge import (
    _archive_stale_plans,
    _live_remote_branches_sanitized,
)


def test_archive_stale_plans_removes_deleted_branch(kb_repo: Path, capsys):
    # Sanitized dir name
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-merged"
    active.mkdir(parents=True)
    (active / "plan.md").write_text("# Plan\n\n**Status:** in-progress\n")

    with patch("reinicorn.commands.internal.post_merge.run_git") as mock_git, \
         patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.repo_root", return_value=kb_repo):
        # No remote branches — everything should be archived
        mock_git.return_value.stdout = ""
        _archive_stale_plans(kb_repo)

    assert not active.is_dir()
    completed = (
        kb_repo / "kb" / "testproject" / "exec-plans" / "completed" / "feature-merged"
    )
    assert completed.is_dir()


def test_archive_stale_plans_keeps_existing_branch(kb_repo: Path):
    # Sanitized dir name
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-open"
    active.mkdir(parents=True)
    (active / "plan.md").write_text("# Plan\n\n**Status:** in-progress\n")

    with patch("reinicorn.commands.internal.post_merge.run_git") as mock_git:
        # Remote branch exists — feature/open sanitizes to feature-open
        mock_git.return_value.stdout = "  origin/feature/open\n"
        _archive_stale_plans(kb_repo)

    assert active.is_dir()


def test_live_remote_branches_sanitized(kb_repo: Path):
    with patch("reinicorn.commands.internal.post_merge.run_git") as mock_git:
        mock_git.return_value.stdout = (
            "  origin/main\n"
            "  origin/feature/mvp\n"
            "  origin/fix/bug-123\n"
            "  origin/HEAD -> origin/main\n"
        )
        result = _live_remote_branches_sanitized(kb_repo)

    assert result == {"main", "feature-mvp", "fix-bug-123"}


def test_live_remote_branches_sanitized_returns_none_on_error(kb_repo: Path):
    with patch("reinicorn.commands.internal.post_merge.run_git", side_effect=Exception("fail")):
        result = _live_remote_branches_sanitized(kb_repo)

    assert result is None


def test_archive_stale_plans_skips_on_git_error(kb_repo: Path):
    """Verify that git failures don't silently archive all plans."""
    active = (
        kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-important"
    )
    active.mkdir(parents=True)
    (active / "plan.md").write_text("# Plan\n\n**Status:** in-progress\n")

    with patch(
        "reinicorn.commands.internal.post_merge.run_git",
        side_effect=Exception("no network"),
    ), patch("reinicorn.kb.kb_scope", return_value="testproject"):
        _archive_stale_plans(kb_repo)

    # Plan must still be in active/ — NOT archived
    assert active.is_dir()
    assert (active / "plan.md").is_file()
