"""Tests for reins _pre-push — kb submodule sync."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.internal.pre_push import _ensure_kb_pushed
from reinicorn.git import run_git


class TestEnsureKbPushed:
    """Tests for synchronous kb push before parent push."""

    def test_no_kb_dir_returns_zero(self, tmp_path: Path):
        """No kb submodule → nothing to do."""
        with patch(
            "reinicorn.commands.internal.pre_push.get_kb_dir", return_value=None
        ):
            assert _ensure_kb_pushed(tmp_path) == 0

    def test_disabled_mode_skips(self, submodule_repo: Path):
        """Disabled mode → skip kb push check."""
        state_dir = submodule_repo / ".reinicorn"
        state_dir.mkdir()
        (state_dir / "mode").write_text("disabled")
        assert _ensure_kb_pushed(submodule_repo) == 0

    def test_incognito_mode_skips(self, submodule_repo: Path):
        """Incognito mode → skip kb push check."""
        state_dir = submodule_repo / ".reinicorn"
        state_dir.mkdir()
        (state_dir / "mode").write_text("incognito")
        assert _ensure_kb_pushed(submodule_repo) == 0

    def test_already_pushed_returns_zero(self, submodule_repo: Path):
        """Kb HEAD already on remote → returns 0, no push attempted."""
        # submodule_repo starts with kb in sync with remote
        assert _ensure_kb_pushed(submodule_repo) == 0

    def test_unpushed_kb_auto_pushes(self, submodule_repo: Path):
        """Kb has unpushed commits → auto-push succeeds, returns 0."""
        kb = submodule_repo / "kb"

        # Make a new commit in the kb (unpushed)
        (kb / "new-file.md").write_text("new content\n")
        run_git("add", "-A", cwd=kb)
        run_git("commit", "-q", "-m", "new kb content", cwd=kb)

        # Update parent's submodule pointer to reference the new commit
        run_git("add", "kb", cwd=submodule_repo)
        run_git("commit", "-q", "-m", "update kb pointer", cwd=submodule_repo)

        # The kb commit is NOT on the remote yet
        local_sha = run_git("rev-parse", "HEAD", cwd=kb).stdout.strip()
        remote_sha = run_git("rev-parse", "origin/main", cwd=kb).stdout.strip()
        assert local_sha != remote_sha, "precondition: kb should be ahead of remote"

        # _ensure_kb_pushed should auto-push and return 0
        result = _ensure_kb_pushed(submodule_repo)
        assert result == 0

        # Verify the commit is now on the remote
        run_git("fetch", "origin", cwd=kb)
        remote_sha_after = run_git("rev-parse", "origin/main", cwd=kb).stdout.strip()
        assert remote_sha_after == local_sha

    def test_push_failure_blocks_with_error(self, submodule_repo: Path, capsys):
        """Kb push fails → returns 1 with error message."""
        kb = submodule_repo / "kb"

        # Make an unpushed commit
        (kb / "new-file.md").write_text("content\n")
        run_git("add", "-A", cwd=kb)
        run_git("commit", "-q", "-m", "unpushed", cwd=kb)
        run_git("add", "kb", cwd=submodule_repo)
        run_git("commit", "-q", "-m", "update pointer", cwd=submodule_repo)

        # Make the push fail by pointing origin to a nonexistent path
        run_git("remote", "set-url", "origin", "/nonexistent/path", cwd=kb)

        result = _ensure_kb_pushed(submodule_repo)
        assert result == 1

        captured = capsys.readouterr()
        assert "Kb push failed" in captured.out
        assert "cd kb && git push origin main" in captured.out

    def test_no_git_dir_in_kb_skips(self, submodule_repo: Path):
        """Kb exists but no .git → skip (not a real submodule)."""
        kb = submodule_repo / "kb"
        # Remove .git to simulate a non-submodule kb dir
        git_path = kb / ".git"
        if git_path.is_file():
            git_path.unlink()
        elif git_path.is_dir():
            import shutil
            shutil.rmtree(git_path)

        assert _ensure_kb_pushed(submodule_repo) == 0


def test_cmd_pre_push_fails_closed_on_unexpected_error(capsys):
    """An unexpected error in the check blocks the push (fail closed)."""
    from reinicorn.commands.internal import pre_push

    with patch.object(
        pre_push, "repo_root", side_effect=RuntimeError("boom")
    ):
        assert pre_push.cmd_pre_push() == 1

    assert "Refusing the push" in capsys.readouterr().out


def test_cmd_pre_push_does_not_dirty_kb(submodule_repo: Path, monkeypatch):
    """cmd_pre_push must never write to the kb submodule."""
    from reinicorn.commands.internal.pre_push import cmd_pre_push

    kb = submodule_repo / "kb"

    # Create a feature branch so there is a real merge-base diff vs main.
    run_git("checkout", "-q", "-b", "feature-test", cwd=submodule_repo)

    # Create an active exec-plan dir for the feature branch inside the kb.
    # The plan dir must be nested under a repo-slug subdir; "unknown" matches
    # what repo_slug() returns when the parent repo has no remote.
    slug = "unknown"
    active = kb / slug / "exec-plans" / "active" / "feature-test"
    active.mkdir(parents=True)
    (active / "plan.md").write_text("# plan\n")

    # Commit the new plan inside the kb so the kb starts clean.
    run_git("add", "-A", cwd=kb)
    run_git("commit", "-q", "-m", "add plan dir", cwd=kb)
    run_git("add", "kb", cwd=submodule_repo)
    run_git("commit", "-q", "-m", "advance kb", cwd=submodule_repo)

    # Put a committed change in the parent repo so merge-base diff is non-empty.
    (submodule_repo / "src.py").write_text("x = 1\n")
    run_git("add", "src.py", cwd=submodule_repo)
    run_git("commit", "-q", "-m", "wip", cwd=submodule_repo)

    monkeypatch.chdir(submodule_repo)

    before = run_git("-C", "kb", "status", "--porcelain", cwd=submodule_repo).stdout

    rc = cmd_pre_push()
    assert rc == 0

    after = run_git("-C", "kb", "status", "--porcelain", cwd=submodule_repo).stdout

    assert before == after, (
        f"pre-push dirtied kb:\nbefore={before!r}\nafter={after!r}"
    )
