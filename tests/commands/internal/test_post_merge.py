"""Tests for reins _post-merge — stale plan archival.

The real contract (see src/reins/commands/internal/post_merge.py) is not
"branch merged into HEAD" but "branch still has a live origin/* ref":
_archive_stale_plans() diffs each active/<branch>/ dir against the set of
remote-tracking branches (git branch -r --list 'origin/*'). A dir with no
matching origin/* ref is treated as stale (its remote branch was deleted,
e.g. via GitHub's "delete branch on merge") and gets archived to completed/
via plan.cmd_plan_complete(). A dir that still has a live origin/* ref is
left alone. If querying the remote errors out, nothing is archived.

cmd_post_merge() takes no arguments (invoked from the hook as
`reins _post-merge` with no flags parsed). Like its sibling hooks, it is
gated on hook_check() — disabled mode is a no-op — and it also no-ops
when not in a repo or when no kb submodule is configured.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.internal.post_merge import cmd_post_merge
from reinicorn.git import run_git


def _mk_active_plan(repo: Path, slug: str, branch_dir: str) -> Path:
    """Create + commit an active exec-plan dir inside the kb submodule."""
    active = repo / "kb" / slug / "exec-plans" / "active" / branch_dir
    active.mkdir(parents=True)
    (active / "plan.md").write_text(
        f"# Execution Plan: {branch_dir}\n\n**Status:** in-progress\n"
    )
    run_git("add", "-A", cwd=repo / "kb")
    run_git("commit", "-q", "-m", "plan", cwd=repo / "kb")
    return active


def _add_origin(repo: Path, tmp_path: Path) -> None:
    """Give the parent repo a real 'origin' remote with main pushed.

    Named "unknown.git" so repo_slug() (which reads the origin URL) still
    resolves to "unknown", matching the exec-plan repo-scope dir used by
    the sibling internal-hook tests when there's no real project remote.
    """
    bare = tmp_path / "unknown.git"
    run_git("init", "-q", "--bare", str(bare))
    run_git("remote", "add", "origin", str(bare), cwd=repo)
    run_git("push", "-q", "origin", "main", cwd=repo)


def test_disabled_mode_is_noop(submodule_repo: Path, monkeypatch):
    """Disabled mode → no archival, even for a stale plan."""
    state_dir = submodule_repo / ".reinicorn"
    state_dir.mkdir()
    (state_dir / "mode").write_text("disabled")
    slug = "unknown"
    active = submodule_repo / "kb" / slug / "exec-plans" / "active" / "feature-stale"
    active.mkdir(parents=True)
    (active / "plan.md").write_text(
        "# Execution Plan: feature-stale\n\n**Status:** in-progress\n"
    )
    monkeypatch.chdir(submodule_repo)
    assert cmd_post_merge() == 0
    assert (active / "plan.md").is_file()  # untouched


def test_no_repo_is_noop(tmp_path: Path, monkeypatch):
    """Outside any git repo, repo_root() is None → clean no-op."""
    monkeypatch.chdir(tmp_path)
    assert cmd_post_merge() == 0


def test_no_kb_dir_is_noop(submodule_repo: Path, monkeypatch):
    """No kb submodule configured → nothing to archive."""
    monkeypatch.chdir(submodule_repo)
    with patch("reinicorn.commands.internal.post_merge.get_kb_dir", return_value=None):
        assert cmd_post_merge() == 0


def test_branch_without_remote_is_archived(submodule_repo: Path, monkeypatch, tmp_path: Path):
    """A plan whose branch has no matching origin/* ref is stale → archived.

    This is the common post-merge state: the feature branch was merged and
    its remote branch deleted (e.g. GitHub's "delete branch on merge"), so
    by the time the hook runs there is no origin/feature-done ref left.
    """
    slug = "unknown"
    _add_origin(submodule_repo, tmp_path)

    run_git("checkout", "-q", "-b", "feature-done", cwd=submodule_repo)
    (submodule_repo / "f.txt").write_text("x\n")
    run_git("add", "f.txt", cwd=submodule_repo)
    run_git("commit", "-q", "-m", "work", cwd=submodule_repo)
    run_git("checkout", "-q", "main", cwd=submodule_repo)
    run_git("merge", "-q", "feature-done", cwd=submodule_repo)
    # feature-done is merged locally but was never pushed, so no origin/*
    # ref for it ever existed — equivalent to "already deleted upstream".

    _mk_active_plan(submodule_repo, slug, "feature-done")
    monkeypatch.chdir(submodule_repo)

    assert cmd_post_merge() == 0
    assert not (
        submodule_repo / "kb" / slug / "exec-plans" / "active" / "feature-done"
    ).exists()
    assert (
        submodule_repo / "kb" / slug / "exec-plans" / "completed" / "feature-done" / "plan.md"
    ).is_file()


def test_branch_with_live_remote_is_kept(submodule_repo: Path, monkeypatch, tmp_path: Path):
    """A plan whose branch still has a live origin/* ref stays in active/."""
    slug = "unknown"
    _add_origin(submodule_repo, tmp_path)

    run_git("checkout", "-q", "-b", "feature-wip", cwd=submodule_repo)
    (submodule_repo / "g.txt").write_text("y\n")
    run_git("add", "g.txt", cwd=submodule_repo)
    run_git("commit", "-q", "-m", "wip", cwd=submodule_repo)
    run_git("push", "-q", "origin", "feature-wip", cwd=submodule_repo)
    run_git("checkout", "-q", "main", cwd=submodule_repo)

    _mk_active_plan(submodule_repo, slug, "feature-wip")
    monkeypatch.chdir(submodule_repo)

    assert cmd_post_merge() == 0
    assert (
        submodule_repo / "kb" / slug / "exec-plans" / "active" / "feature-wip" / "plan.md"
    ).is_file()


def test_remote_query_error_keeps_plan(submodule_repo: Path, monkeypatch):
    """If querying origin/* branches errors out, archiving is skipped entirely."""
    slug = "unknown"
    _mk_active_plan(submodule_repo, slug, "feature-x")
    monkeypatch.chdir(submodule_repo)

    with patch(
        "reinicorn.commands.internal.post_merge.run_git", side_effect=OSError("boom"),
    ):
        assert cmd_post_merge() == 0

    assert (
        submodule_repo / "kb" / slug / "exec-plans" / "active" / "feature-x" / "plan.md"
    ).is_file()
