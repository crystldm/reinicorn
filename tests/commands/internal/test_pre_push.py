"""Tests for rcorn _pre-push — kb publication and the review-lane gate."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

from tests.conftest import doc_text

from reinicorn.commands.internal.deps_gate import ensure_dependencies_approved
from reinicorn.commands.internal.pre_push import _ensure_kb_pushed
from reinicorn.git import run_git, sanitize_branch


class TestEnsureKbPushed:
    """Tests for synchronous kb push before parent push."""

    def test_no_kb_dir_returns_zero(self, tmp_path: Path):
        """No kb → nothing to do."""
        with patch(
            "reinicorn.commands.internal.pre_push.get_kb_dir", return_value=None
        ):
            assert _ensure_kb_pushed(tmp_path) == 0

    def test_disabled_mode_skips(self, kb_clone_repo: Path):
        """Disabled mode → skip kb push check."""
        state_dir = kb_clone_repo / ".reinicorn"
        state_dir.mkdir()
        (state_dir / "mode").write_text("disabled")
        assert _ensure_kb_pushed(kb_clone_repo) == 0

    def test_incognito_mode_skips(self, kb_clone_repo: Path):
        """Incognito mode → skip kb push check."""
        state_dir = kb_clone_repo / ".reinicorn"
        state_dir.mkdir()
        (state_dir / "mode").write_text("incognito")
        assert _ensure_kb_pushed(kb_clone_repo) == 0

    def test_pre_push_noop_when_kb_current(self, kb_clone_repo: Path):
        """Kb main already matches origin/main → returns 0, no push attempted."""
        assert _ensure_kb_pushed(kb_clone_repo) == 0

    def test_pre_push_pushes_ahead_kb(
        self, kb_clone_repo: Path, monkeypatch, tmp_path
    ):
        """Local kb main ahead of origin/main gets pushed before the parent push."""
        kb = kb_clone_repo / "kb"
        (kb / "doc.md").write_text("x\n")
        run_git("add", "-A", cwd=kb)
        run_git("commit", "-q", "-m", "local doc", cwd=kb)
        monkeypatch.chdir(kb_clone_repo)

        assert _ensure_kb_pushed(kb_clone_repo) == 0
        # The commit reached the bare remote itself, not just the local
        # origin/main tracking ref.
        assert run_git("rev-parse", "main", cwd=kb).stdout == run_git(
            "--git-dir", str(tmp_path / "kb-remote"), "rev-parse", "main"
        ).stdout

    def test_push_failure_blocks_with_error(self, kb_clone_repo: Path, capsys):
        """Kb push fails → returns 1 with error message."""
        kb = kb_clone_repo / "kb"

        # Make an unpushed commit
        (kb / "new-file.md").write_text("content\n")
        run_git("add", "-A", cwd=kb)
        run_git("commit", "-q", "-m", "unpushed", cwd=kb)

        # Make the push fail by pointing origin to a nonexistent path
        run_git("remote", "set-url", "origin", "/nonexistent/path", cwd=kb)

        result = _ensure_kb_pushed(kb_clone_repo)
        assert result == 1

        captured = capsys.readouterr()
        assert "Could not push the kb" in captured.out
        # The hook used to print only its own prose; git's reason for refusing
        # is what actually tells the user what to fix.
        assert "git: " in captured.out
        assert "/nonexistent/path" in captured.out
        assert "rcorn kb publish" in captured.out

    def test_no_git_dir_in_kb_skips(self, kb_clone_repo: Path):
        """Kb exists but no .git → skip (not a real kb clone)."""
        kb = kb_clone_repo / "kb"
        # Remove .git to simulate a non-kb directory
        git_path = kb / ".git"
        if git_path.is_file():
            git_path.unlink()
        elif git_path.is_dir():
            import shutil
            shutil.rmtree(git_path)

        assert _ensure_kb_pushed(kb_clone_repo) == 0


def test_cmd_pre_push_fails_closed_on_unexpected_error(capsys):
    """An unexpected error in the check blocks the push (fail closed)."""
    from reinicorn.commands.internal import pre_push

    with patch.object(
        pre_push, "repo_root", side_effect=RuntimeError("boom")
    ):
        assert pre_push.cmd_pre_push() == 1

    assert "Refusing the push" in capsys.readouterr().out


def test_cmd_pre_push_fails_closed_when_stdin_probe_explodes(capsys):
    """Reading the hook's stdin happens inside the fail-closed try.

    A closed (not absent) stdin raises ValueError from isatty(); that must
    reach the handler as a refused push, not escape as a raw traceback.
    """
    from reinicorn.commands.internal import pre_push

    with patch.object(
        pre_push, "_pushed_branches",
        side_effect=ValueError("I/O operation on closed file"),
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
    (active / "plan.md").write_text(doc_text(
        type="plan", title="Plan", slug="plan", status="planning",
        branch="feature/test", spec="N/A", body="\n# plan\n",
    ))

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
        """Put the parent on `branch` with an optional plan + spec committed to the kb."""
        run_git("checkout", "-q", "-b", branch, cwd=repo)
        kb = repo / "kb"

        if spec is not None:
            rel, status = spec
            path = kb / self.SCOPE / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(doc_text(
                title="Doc", slug="doc", status=status,
                body="\n# Doc\n\n## Problem\n\nbody\n",
            ))

        if plan is not None:
            pdir = kb / self.SCOPE / "exec-plans" / "active" / sanitize_branch(branch)
            pdir.mkdir(parents=True, exist_ok=True)
            (pdir / "plan.md").write_text(plan)

        self._commit_kb(kb)

    @staticmethod
    def _commit_kb(kb: Path) -> None:
        """Commit whatever is dirty in the kb clone.

        The gate reads the kb clone's committed HEAD, so a doc only exists
        for it once committed here — there is no parent-side pointer to bump
        anymore. Tolerates emptiness so setups that add nothing still work.
        """
        run_git("add", "-A", cwd=kb)
        run_git("commit", "-q", "-m", "kb docs", cwd=kb, check=False)

    @staticmethod
    def _plan(spec_value: str, branch: str = "feat/thing") -> str:
        return doc_text(
            type="plan", title="Plan", slug="plan", status="planning",
            branch=branch, spec=spec_value,
            body="\n# Plan\n\n## Goal\n\nx\n",
        )

    def _run(self, repo: Path, branches: list[str] | None = None) -> int:
        with patch(
            "reinicorn.commands.internal.deps_gate.kb_scope", return_value=self.SCOPE
        ):
            if branches is None:
                branches = ["feat/thing"]
            return ensure_dependencies_approved(repo, branches)

    def test_no_kb_dir_allows(self, tmp_path: Path):
        with patch(
            "reinicorn.commands.internal.deps_gate.get_kb_dir", return_value=None
        ):
            assert ensure_dependencies_approved(tmp_path, ["feat/thing"]) == 0

    def test_no_plan_for_branch_allows(self, kb_clone_repo: Path):
        self._setup(kb_clone_repo)
        assert self._run(kb_clone_repo) == 0

    def test_not_applicable_allows(self, kb_clone_repo: Path):
        self._setup(kb_clone_repo, plan=self._plan("N/A"))
        assert self._run(kb_clone_repo) == 0

    def test_approved_spec_allows(self, kb_clone_repo: Path):
        self._setup(
            kb_clone_repo,
            plan=self._plan("specs/ok.md"),
            spec=("specs/ok.md", "approved"),
        )
        assert self._run(kb_clone_repo) == 0

    def test_non_spec_doc_blocks(self, kb_clone_repo: Path, capsys):
        """A tracked doc outside specs/ must not satisfy the field.

        It resolves, and carries no review status for `unapproved_reason` to
        object to, so without a doc-type check it would pass the gate.
        """
        self._setup(
            kb_clone_repo,
            plan=self._plan("references/git-notes.md"),
            spec=("references/git-notes.md", "n/a"),
        )
        assert self._run(kb_clone_repo) == 1
        assert "is not a spec" in capsys.readouterr().out

    def test_in_review_spec_blocks(self, kb_clone_repo: Path, capsys):
        self._setup(
            kb_clone_repo,
            plan=self._plan("specs/hot.md"),
            spec=("specs/hot.md", "in-review"),
        )
        assert self._run(kb_clone_repo) == 1
        out = capsys.readouterr().out
        assert "Push blocked" in out
        assert "specs/hot.md" in out
        assert "rcorn review status hot" in out
        assert "--no-verify" in out

    def test_draft_spec_blocks(self, kb_clone_repo: Path, capsys):
        self._setup(
            kb_clone_repo,
            plan=self._plan("specs/drafts/wip.md"),
            spec=("specs/drafts/wip.md", "draft"),
        )
        assert self._run(kb_clone_repo) == 1
        assert "drafts" in capsys.readouterr().out

    def test_drafts_fallback_blocks_on_future_approved_path(
        self, kb_clone_repo: Path, capsys
    ):
        """Citing the path the spec *will* have while it is still a draft."""
        self._setup(
            kb_clone_repo,
            plan=self._plan("specs/wip.md"),
            spec=("specs/drafts/wip.md", "in-review"),
        )
        assert self._run(kb_clone_repo) == 1
        assert "specs/drafts/wip.md" in capsys.readouterr().out

    def test_missing_spec_field_blocks(self, kb_clone_repo: Path, capsys):
        """Omitting the field must not be a way to dodge the gate."""
        self._setup(kb_clone_repo, plan="# Plan\n\n## Goal\n\nx\n")
        assert self._run(kb_clone_repo) == 1
        assert "missing or still the template placeholder" in capsys.readouterr().out

    def test_placeholder_spec_field_blocks(self, kb_clone_repo: Path):
        self._setup(
            kb_clone_repo,
            plan=self._plan("[kb path to the spec this implements, or N/A]"),
        )
        assert self._run(kb_clone_repo) == 1

    def test_unresolved_spec_blocks(self, kb_clone_repo: Path, capsys):
        """Cannot determine approval is an error state, not a pass."""
        self._setup(kb_clone_repo, plan=self._plan("specs/typo.md"))
        assert self._run(kb_clone_repo) == 1
        assert "matches no path in the kb commit" in capsys.readouterr().out

    def test_staged_but_uncommitted_spec_blocks(self, kb_clone_repo: Path):
        """The index is desk state, not what ships.

        A spec staged in the kb but absent from its committed HEAD is
        invisible to whoever checks the kb clone out at that HEAD — resolving
        against `ls-files` would let it satisfy the gate anyway.
        """
        self._setup(kb_clone_repo, plan=self._plan("specs/ghost.md"))
        ghost = kb_clone_repo / "kb" / self.SCOPE / "specs" / "ghost.md"
        ghost.parent.mkdir(parents=True, exist_ok=True)
        ghost.write_text(doc_text(title="Ghost", slug="ghost", status="approved"))
        run_git("add", "-A", cwd=kb_clone_repo / "kb")  # staged, never committed
        assert self._run(kb_clone_repo) == 1

    def test_worktree_status_edit_does_not_launder_a_draft(
        self, kb_clone_repo: Path, capsys
    ):
        """Editing the status on disk without committing must change nothing."""
        self._setup(
            kb_clone_repo,
            plan=self._plan("specs/hot.md"),
            spec=("specs/hot.md", "in-review"),
        )
        doctored = kb_clone_repo / "kb" / self.SCOPE / "specs" / "hot.md"
        doctored.write_text(doc_text(title="Doc", slug="doc", status="approved"))
        assert self._run(kb_clone_repo) == 1
        assert "in-review" in capsys.readouterr().out

    def test_ambiguous_spec_blocks(self, kb_clone_repo: Path, capsys):
        self._setup(
            kb_clone_repo,
            plan=self._plan("specs/dup.md"),
            spec=("specs/dup.md", "approved"),
        )
        top = kb_clone_repo / "kb" / "specs"
        top.mkdir(parents=True, exist_ok=True)
        (top / "dup.md").write_text(doc_text(title="Other", slug="other", status="approved"))
        self._commit_kb(kb_clone_repo / "kb")
        assert self._run(kb_clone_repo) == 1
        assert "ambiguous" in capsys.readouterr().out

    def test_disabled_mode_skips(self, kb_clone_repo: Path):
        self._setup(kb_clone_repo, plan=self._plan("specs/typo.md"))
        state = kb_clone_repo / ".reinicorn"
        state.mkdir(exist_ok=True)
        (state / "mode").write_text("disabled")
        assert self._run(kb_clone_repo) == 0

    def test_incognito_mode_skips(self, kb_clone_repo: Path):
        self._setup(kb_clone_repo, plan=self._plan("specs/typo.md"))
        state = kb_clone_repo / ".reinicorn"
        state.mkdir(exist_ok=True)
        (state / "mode").write_text("incognito")
        assert self._run(kb_clone_repo) == 0

    def test_exception_fails_open_and_says_so(self, kb_clone_repo: Path, capsys):
        """Unlike _ensure_kb_pushed, a policy gate must not brick every push.

        But it must be loud — a silently degraded gate is indistinguishable from
        one that was never wired up.
        """
        self._setup(kb_clone_repo, plan=self._plan("specs/hot.md"))
        with patch(
            "reinicorn.commands.internal.deps_gate.tracked_paths_at",
            side_effect=RuntimeError("boom"),
        ):
            assert self._run(kb_clone_repo) == 0
        out = capsys.readouterr().out
        assert "Dependency-approval gate did not run" in out
        assert "boom" in out
        assert "feat/thing" in out
        assert "NOT checked" in out

    def test_checks_the_pushed_branch_not_the_checked_out_one(
        self, kb_clone_repo: Path, capsys
    ):
        """`git push origin other-branch` must check *that* branch's plan.

        Resolving from HEAD would let the gate be bypassed by pushing a branch
        that is not checked out — an ordinary workflow, not a workaround.
        """
        self._setup(
            kb_clone_repo, "feat/other",
            plan=self._plan("specs/hot.md", branch="feat/other"),
            spec=("specs/hot.md", "in-review"),
        )
        run_git("checkout", "-q", "main", cwd=kb_clone_repo)
        assert self._run(kb_clone_repo, ["feat/other"]) == 1
        assert "specs/hot.md" in capsys.readouterr().out

    def test_multi_ref_push_blocks_on_any_offending_branch(
        self, kb_clone_repo: Path, capsys
    ):
        self._setup(
            kb_clone_repo, "feat/clean",
            plan=self._plan("N/A", branch="feat/clean"),
        )
        self._setup(
            kb_clone_repo, "feat/dirty",
            plan=self._plan("specs/wip.md", branch="feat/dirty"),
            spec=("specs/drafts/wip.md", "draft"),
        )
        assert self._run(kb_clone_repo, ["feat/clean", "feat/dirty"]) == 1
        assert "feat-dirty" in capsys.readouterr().out

    def test_no_branches_allows(self, kb_clone_repo: Path):
        """A push with no branch refs (tags only) has no plan to check."""
        self._setup(kb_clone_repo, plan=self._plan("specs/typo.md"))
        assert self._run(kb_clone_repo, []) == 0

    def test_empty_kb_clone_allows_quietly(self, kb_clone_repo: Path, capsys):
        """An unborn HEAD (rev-parse exit 1) is a real state — a freshly
        initialized kb — and skipping it is expected, not a degraded gate."""
        shutil.rmtree(kb_clone_repo / "kb")
        run_git("init", "-q", str(kb_clone_repo / "kb"))
        assert self._run(kb_clone_repo) == 0
        assert "did not run" not in capsys.readouterr().out

    def test_broken_kb_head_fails_open_loudly(self, kb_clone_repo: Path, capsys):
        """rev-parse failing for any reason other than an unborn HEAD is a
        broken kb, not an empty one — silently skipping would hide a
        degraded gate."""
        self._setup(kb_clone_repo, plan=self._plan("specs/hot.md"))
        # A gitfile naming a missing gitdir is definitively broken (exit 128);
        # corrupting HEAD instead would let git discovery escape to the parent.
        shutil.rmtree(kb_clone_repo / "kb" / ".git")
        (kb_clone_repo / "kb" / ".git").write_text("gitdir: /nonexistent/kb-git\n")
        assert self._run(kb_clone_repo) == 0
        out = capsys.readouterr().out
        assert "Dependency-approval gate did not run" in out
        assert "NOT checked" in out

    def test_git_failure_fails_open_loudly(self, kb_clone_repo: Path, capsys):
        """A broken kb must not read as 'every spec unresolved' and block.

        tracked_paths raising is what routes this to the loud fail-open path
        instead of a misleading 'matches no git-tracked kb path' block.
        """
        self._setup(
            kb_clone_repo,
            plan=self._plan("specs/ok.md"),
            spec=("specs/ok.md", "approved"),
        )
        with patch(
            "reinicorn.commands.internal.deps_gate.tracked_paths_at",
            side_effect=RuntimeError("git ls-tree failed"),
        ):
            assert self._run(kb_clone_repo) == 0
        out = capsys.readouterr().out
        assert "did not run" in out
        assert "NOT checked" in out


class TestPushedBranches:
    """Parsing the pre-push hook's stdin ref list."""

    def _parse(self, monkeypatch, text: str) -> list[str]:
        import io

        from reinicorn.commands.internal import pre_push

        stream = io.StringIO(text)
        stream.isatty = lambda: False  # type: ignore[method-assign]
        monkeypatch.setattr(pre_push.sys, "stdin", stream)
        return pre_push._pushed_branches()

    def test_parses_single_ref(self, monkeypatch):
        assert self._parse(
            monkeypatch,
            "refs/heads/feat/x abc123 refs/heads/feat/x def456\n",
        ) == ["feat/x"]

    def test_parses_multiple_refs(self, monkeypatch):
        out = self._parse(
            monkeypatch,
            "refs/heads/a 111 refs/heads/a 222\n"
            "refs/heads/b 333 refs/heads/b 444\n",
        )
        assert out == ["a", "b"]

    def test_skips_deletions(self, monkeypatch):
        assert self._parse(
            monkeypatch,
            f"(delete) {'0' * 40} refs/heads/gone 999\n"
            f"refs/heads/kept {'0' * 40} refs/heads/kept 888\n"
            "refs/heads/live 777 refs/heads/live 666\n",
        ) == ["live"]

    def test_skips_non_branch_refs(self, monkeypatch):
        assert self._parse(
            monkeypatch,
            "refs/tags/v1 abc refs/tags/v1 def\n",
        ) == []

    def test_empty_stdin_returns_empty(self, monkeypatch):
        assert self._parse(monkeypatch, "") == []

    def test_tty_stdin_returns_none(self, monkeypatch):
        """Invoked by hand, not by the hook — caller falls back to HEAD.

        None and [] are different answers: None is 'no hook context, use HEAD',
        [] is 'the hook named no branches, check nothing'.
        """
        import io

        from reinicorn.commands.internal import pre_push

        stream = io.StringIO("")
        stream.isatty = lambda: True  # type: ignore[method-assign]
        monkeypatch.setattr(pre_push.sys, "stdin", stream)
        assert pre_push._pushed_branches() is None

    def test_absent_stdin_returns_none(self, monkeypatch):
        from reinicorn.commands.internal import pre_push

        monkeypatch.setattr(pre_push.sys, "stdin", None)
        assert pre_push._pushed_branches() is None


class TestPushedBranchSelection:
    """Which branches cmd_pre_push hands the gate, given what the hook saw."""

    def _run(
        self, monkeypatch, pushed: list[str] | None, *, patch_branch: bool = True
    ) -> list[str]:
        """Return the branch list the gate was called with."""
        from reinicorn.commands.internal import pre_push

        seen: list[list[str]] = []
        monkeypatch.setattr(pre_push, "_pushed_branches", lambda: pushed)
        if patch_branch:
            monkeypatch.setattr(pre_push, "current_branch", lambda: "checked-out")
        # Called as repo_root(quiet=True), so accept the keyword.
        monkeypatch.setattr(pre_push, "repo_root", lambda **_: Path("/repo"))
        monkeypatch.setattr(
            pre_push, "_ensure_kb_pushed", lambda _root: 0
        )
        monkeypatch.setattr(
            pre_push, "ensure_dependencies_approved",
            lambda _root, branches: (seen.append(branches), 0)[1],
        )
        assert pre_push.cmd_pre_push() == 0
        return seen[0]

    def test_tag_only_push_checks_nothing(self, monkeypatch):
        """The reported bug: `git push origin v1.2.0` names no branch.

        Falling back to HEAD here would judge an unrelated tag push against
        whatever plan happened to be checked out, and could block it.
        """
        assert self._run(monkeypatch, []) == []

    def test_no_hook_context_falls_back_to_head(self, monkeypatch):
        assert self._run(monkeypatch, None) == ["checked-out"]

    def test_detached_head_falls_back_to_head_rev(self, monkeypatch):
        """No branch name while detached — 'HEAD' still names the kb pointer.

        The kb-push check can verify a detached checkout's pointer; the gate
        finds no plan for a subject named 'HEAD' and skips, which is the best
        either can do without a branch.
        """
        from reinicorn.commands.internal import pre_push

        monkeypatch.setattr(pre_push, "current_branch", lambda: "")
        assert self._run(monkeypatch, None, patch_branch=False) == ["HEAD"]

    def test_pushed_branches_are_used_verbatim(self, monkeypatch):
        assert self._run(monkeypatch, ["a", "b"]) == ["a", "b"]
