"""Tests for reins _pre-push — kb submodule sync."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.internal.pre_push import (
    _ensure_kb_pushed,
    _ensure_plan_spec_approved,
)
from reinicorn.git import run_git, sanitize_branch


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
        assert "Could not push the kb" in captured.out
        # The hook used to print only its own prose; git's reason for refusing
        # is what actually tells the user what to fix.
        assert "git: " in captured.out
        assert "/nonexistent/path" in captured.out
        assert "rcorn kb publish" in captured.out

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
    # Spec: N/A so the review-lane gate passes — this test is about the kb
    # staying clean, not about the gate.
    (active / "plan.md").write_text("# plan\n\n**Spec:** N/A\n**Status:** planning\n")

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


class TestEnsurePlanSpecApproved:
    """The review-lane gate: refuse a push whose plan builds on an unapproved spec."""

    SCOPE = "testproject"

    def _setup(
        self, repo: Path, branch: str = "feat/thing", *,
        plan: str | None = None, spec: tuple[str, str] | None = None,
    ) -> None:
        """Put the parent on `branch` and stage an optional plan + spec in the kb."""
        run_git("checkout", "-q", "-b", branch, cwd=repo)
        kb = repo / "kb"

        if spec is not None:
            rel, status = spec
            path = kb / self.SCOPE / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# Doc\n\n**Status:** {status}\n\n## Problem\n\nbody\n")

        if plan is not None:
            pdir = kb / self.SCOPE / "exec-plans" / "active" / sanitize_branch(branch)
            pdir.mkdir(parents=True, exist_ok=True)
            (pdir / "plan.md").write_text(plan)

        run_git("add", "-A", cwd=kb)

    @staticmethod
    def _plan(spec_value: str) -> str:
        return f"# Plan\n\n**Spec:** {spec_value}\n**Status:** planning\n\n## Goal\n\nx\n"

    def _run(self, repo: Path) -> int:
        with patch(
            "reinicorn.commands.internal.pre_push.kb_scope", return_value=self.SCOPE
        ):
            return _ensure_plan_spec_approved(repo)

    def test_no_kb_dir_allows(self, tmp_path: Path):
        with patch(
            "reinicorn.commands.internal.pre_push.get_kb_dir", return_value=None
        ):
            assert _ensure_plan_spec_approved(tmp_path) == 0

    def test_no_plan_for_branch_allows(self, submodule_repo: Path):
        self._setup(submodule_repo)
        assert self._run(submodule_repo) == 0

    def test_not_applicable_allows(self, submodule_repo: Path):
        self._setup(submodule_repo, plan=self._plan("N/A"))
        assert self._run(submodule_repo) == 0

    def test_approved_spec_allows(self, submodule_repo: Path):
        self._setup(
            submodule_repo,
            plan=self._plan("specs/ok.md"),
            spec=("specs/ok.md", "approved"),
        )
        assert self._run(submodule_repo) == 0

    def test_in_review_spec_blocks(self, submodule_repo: Path, capsys):
        self._setup(
            submodule_repo,
            plan=self._plan("specs/hot.md"),
            spec=("specs/hot.md", "in-review"),
        )
        assert self._run(submodule_repo) == 1
        out = capsys.readouterr().out
        assert "Push blocked" in out
        assert "specs/hot.md" in out
        assert "rcorn review status hot" in out
        assert "--no-verify" in out

    def test_draft_spec_blocks(self, submodule_repo: Path, capsys):
        self._setup(
            submodule_repo,
            plan=self._plan("specs/drafts/wip.md"),
            spec=("specs/drafts/wip.md", "draft"),
        )
        assert self._run(submodule_repo) == 1
        assert "drafts" in capsys.readouterr().out

    def test_drafts_fallback_blocks_on_future_approved_path(
        self, submodule_repo: Path, capsys
    ):
        """Citing the path the spec *will* have while it is still a draft."""
        self._setup(
            submodule_repo,
            plan=self._plan("specs/wip.md"),
            spec=("specs/drafts/wip.md", "in-review"),
        )
        assert self._run(submodule_repo) == 1
        assert "specs/drafts/wip.md" in capsys.readouterr().out

    def test_missing_spec_field_blocks(self, submodule_repo: Path, capsys):
        """Omitting the field must not be a way to dodge the gate."""
        self._setup(submodule_repo, plan="# Plan\n\n**Status:** planning\n\n## Goal\n\nx\n")
        assert self._run(submodule_repo) == 1
        assert "missing or still the template placeholder" in capsys.readouterr().out

    def test_placeholder_spec_field_blocks(self, submodule_repo: Path):
        self._setup(
            submodule_repo,
            plan=self._plan("[kb path to the spec this implements, or N/A]"),
        )
        assert self._run(submodule_repo) == 1

    def test_unresolved_spec_blocks(self, submodule_repo: Path, capsys):
        """Cannot determine approval is an error state, not a pass."""
        self._setup(submodule_repo, plan=self._plan("specs/typo.md"))
        assert self._run(submodule_repo) == 1
        assert "matches no git-tracked kb path" in capsys.readouterr().out

    def test_untracked_spec_blocks(self, submodule_repo: Path):
        """A spec on disk but never staged does not satisfy the reference."""
        self._setup(submodule_repo, plan=self._plan("specs/ghost.md"))
        ghost = submodule_repo / "kb" / self.SCOPE / "specs" / "ghost.md"
        ghost.parent.mkdir(parents=True, exist_ok=True)
        ghost.write_text("# Ghost\n\n**Status:** approved\n")  # deliberately unstaged
        assert self._run(submodule_repo) == 1

    def test_ambiguous_spec_blocks(self, submodule_repo: Path, capsys):
        self._setup(
            submodule_repo,
            plan=self._plan("specs/dup.md"),
            spec=("specs/dup.md", "approved"),
        )
        top = submodule_repo / "kb" / "specs"
        top.mkdir(parents=True, exist_ok=True)
        (top / "dup.md").write_text("# Other\n\n**Status:** approved\n")
        run_git("add", "-A", cwd=submodule_repo / "kb")
        assert self._run(submodule_repo) == 1
        assert "ambiguous" in capsys.readouterr().out

    def test_disabled_mode_skips(self, submodule_repo: Path):
        self._setup(submodule_repo, plan=self._plan("specs/typo.md"))
        state = submodule_repo / ".reinicorn"
        state.mkdir(exist_ok=True)
        (state / "mode").write_text("disabled")
        assert self._run(submodule_repo) == 0

    def test_incognito_mode_skips(self, submodule_repo: Path):
        self._setup(submodule_repo, plan=self._plan("specs/typo.md"))
        state = submodule_repo / ".reinicorn"
        state.mkdir(exist_ok=True)
        (state / "mode").write_text("incognito")
        assert self._run(submodule_repo) == 0

    def test_exception_fails_open_and_says_so(self, submodule_repo: Path, capsys):
        """Unlike _ensure_kb_pushed, a policy gate must not brick every push.

        But it must be loud — a silently degraded gate is indistinguishable from
        one that was never wired up.
        """
        self._setup(submodule_repo, plan=self._plan("specs/hot.md"))
        with patch(
            "reinicorn.commands.internal.pre_push.tracked_paths",
            side_effect=RuntimeError("boom"),
        ):
            assert self._run(submodule_repo) == 0
        out = capsys.readouterr().out
        assert "Spec-approval gate did not run" in out
        assert "boom" in out
        assert "feat/thing" in out
        assert "NOT checked" in out
