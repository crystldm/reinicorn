"""Tests for reins _post-merge hook — plan archival."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.internal.post_merge import (
    _archive_stale_docs,
    _live_remote_branches,
)
from tests.conftest import doc_text


def test_archive_stale_docs_removes_deleted_branch(kb_repo: Path, capsys):
    # Dir name is sanitized; the branch: field keeps the real ref.
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-merged"
    active.mkdir(parents=True)
    (active / "plan.md").write_text(doc_text(
        type="plan", title="Plan", slug="feature-merged",
        status="in-progress", branch="feature/merged",
        body="\n# Plan\n",
    ))

    with patch("reinicorn.commands.internal.post_merge.run_git") as mock_git, \
         patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.doc_lifecycle.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.doc_lifecycle.repo_root", return_value=kb_repo):
        # No remote branches — everything should be archived
        mock_git.return_value.returncode = 0
        mock_git.return_value.stdout = ""
        _archive_stale_docs(kb_repo)

    assert not active.is_dir()
    completed = (
        kb_repo / "kb" / "testproject" / "exec-plans" / "completed" / "feature-merged"
    )
    assert completed.is_dir()


def test_archive_stale_docs_keeps_existing_branch(kb_repo: Path):
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-open"
    active.mkdir(parents=True)
    (active / "plan.md").write_text(doc_text(
        type="plan", title="Plan", slug="feature-open",
        status="in-progress", branch="feature/open",
        body="\n# Plan\n",
    ))

    with patch("reinicorn.commands.internal.post_merge.run_git") as mock_git:
        mock_git.return_value.returncode = 0
        mock_git.return_value.stdout = "  origin/feature/open\n"
        _archive_stale_docs(kb_repo)

    assert active.is_dir()


def test_lookalike_dashed_branch_does_not_keep_a_deleted_plan_alive(
    kb_repo: Path,
):
    """The bug the frontmatter `branch:` field exists to fix.

    `feature/mvp` is gone, but an unrelated `feature-mvp` branch exists. The
    old comparison sanitized both to `feature-mvp` and treated the plan as
    live; the exact ref must be used instead.
    """
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-mvp"
    active.mkdir(parents=True)
    (active / "plan.md").write_text(doc_text(
        type="plan", title="Plan", slug="feature-mvp",
        status="in-progress", branch="feature/mvp",
        body="\n# Plan\n",
    ))

    with patch("reinicorn.commands.internal.post_merge.run_git") as mock_git, \
         patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.doc_lifecycle.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.doc_lifecycle.repo_root", return_value=kb_repo):
        mock_git.return_value.returncode = 0
        mock_git.return_value.stdout = "  origin/feature-mvp\n"
        _archive_stale_docs(kb_repo)

    assert not active.is_dir(), "plan for the deleted feature/mvp was not archived"


def test_plan_without_a_branch_field_is_never_archived(kb_repo: Path):
    """Archiving is destructive; without a recorded ref there is nothing to
    compare, so the plan must be left alone rather than archived on a guess."""
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "mystery"
    active.mkdir(parents=True)
    (active / "plan.md").write_text("# Plan\n\nno frontmatter at all\n")

    with patch("reinicorn.commands.internal.post_merge.run_git") as mock_git:
        mock_git.return_value.returncode = 0
        mock_git.return_value.stdout = ""
        _archive_stale_docs(kb_repo)

    assert active.is_dir()


def test_live_remote_branches(kb_repo: Path):
    with patch("reinicorn.commands.internal.post_merge.run_git") as mock_git:
        mock_git.return_value.returncode = 0
        mock_git.return_value.stdout = (
            "  origin/main\n"
            "  origin/feature/mvp\n"
            "  origin/fix/bug-123\n"
            "  origin/HEAD -> origin/main\n"
        )
        result = _live_remote_branches(kb_repo)

    # Exact refs, not sanitized: slashes are preserved.
    assert result == {"main", "feature/mvp", "fix/bug-123"}


def test_live_remote_branches_returns_none_on_error(kb_repo: Path):
    with patch("reinicorn.commands.internal.post_merge.run_git", side_effect=Exception("fail")):
        result = _live_remote_branches(kb_repo)

    assert result is None


def test_archive_stale_docs_skips_on_git_error(kb_repo: Path):
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
        _archive_stale_docs(kb_repo)

    # Plan must still be in active/ — NOT archived
    assert active.is_dir()
    assert (active / "plan.md").is_file()


def test_malformed_branch_value_is_not_archived(kb_repo: Path):
    """Archiving is destructive, so an unusable ref means "cannot verify".

    A malformed value would match nothing in live_branches and otherwise be
    read as a deleted branch.
    """
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "weird"
    active.mkdir(parents=True)
    (active / "plan.md").write_text(doc_text(
        type="plan", title="Plan", slug="weird",
        status="in-progress", branch="not a valid ref~^:",
        body="\n# Plan\n",
    ))

    with patch("reinicorn.commands.internal.post_merge.run_git") as mock_git:
        mock_git.return_value.returncode = 1   # check-ref-format rejects it
        mock_git.return_value.stdout = ""
        _archive_stale_docs(kb_repo)

    assert active.is_dir()


def test_failed_remote_query_archives_nothing(kb_repo: Path):
    """`git branch -r` failing with check=False returns normally; an empty
    result must read as "cannot verify", never as "every branch is gone"."""
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-live"
    active.mkdir(parents=True)
    (active / "plan.md").write_text(doc_text(
        type="plan", title="Plan", slug="feature-live",
        status="in-progress", branch="feature/live",
        body="\n# Plan\n",
    ))

    with patch("reinicorn.commands.internal.post_merge.run_git") as mock_git, \
         patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.doc_lifecycle.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.doc_lifecycle.repo_root", return_value=kb_repo):
        mock_git.return_value.returncode = 128
        mock_git.return_value.stdout = ""
        mock_git.return_value.stderr = "fatal: not a git repository"
        _archive_stale_docs(kb_repo)

    assert (active / "plan.md").is_file()
    assert not (
        kb_repo / "kb" / "testproject" / "exec-plans" / "completed" / "feature-live"
    ).exists()
