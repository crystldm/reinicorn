"""Tests for reinicorn.kb."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from reinicorn.doc_types import REGISTRY
from reinicorn.git import run_git
from reinicorn.kb import (
    branch_changed_files,
    commit_kb,
    ensure_kb_on_main,
    get_kb_dir,
    repo_kb_dir,
    require_kb_dir,
)
from reinicorn.staging import (
    STAGE_ACTIVE,
    active_branch_names,
    branch_dir,
    check_overlap,
    overlap_line,
)


def test_get_kb_dir_returns_path(kb_repo: Path):
    assert get_kb_dir(kb_repo) == kb_repo / "kb"


def test_get_kb_dir_returns_none_when_absent(tmp_path: Path):
    assert get_kb_dir(tmp_path) is None


def test_get_kb_dir_requires_git_entry(tmp_path):
    """A kb/ directory without .git is not a kb."""
    root = tmp_path / "repo"
    (root / "kb").mkdir(parents=True)
    assert get_kb_dir(root) is None


def test_get_kb_dir_detects_clone(kb_clone_repo):
    assert get_kb_dir(kb_clone_repo) == kb_clone_repo / "kb"


def test_get_kb_dir_accepts_gitfile(tmp_path):
    """A .git *file* (submodule/worktree checkout) also counts — transition safety."""
    root = tmp_path / "repo"
    kb = root / "kb"
    kb.mkdir(parents=True)
    (kb / ".git").write_text("gitdir: ../.git/modules/kb\n")
    assert get_kb_dir(root) == kb


def test_require_kb_dir_raises_when_none(tmp_path: Path):
    with pytest.raises(SystemExit):
        require_kb_dir(tmp_path)


def test_require_kb_dir_returns_path(kb_repo: Path):
    result = require_kb_dir(kb_repo)
    assert isinstance(result, Path)
    assert result == kb_repo / "kb"


def test_require_kb_dir_error_names_both_paths(tmp_path, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(SystemExit):
        require_kb_dir(root)
    out = capsys.readouterr().out
    assert "rcorn kb sync" in out
    assert "rcorn init" in out


def test_branch_dir(kb_repo: Path):
    result = branch_dir(
        kb_repo / "kb" / "testproject", REGISTRY["plan"], "feature/foo",
        STAGE_ACTIVE,
    )
    expected = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-foo"
    assert result == expected


def test_check_overlap_no_active_plans(kb_repo: Path, capsys):
    result = check_overlap("main", kb_repo)
    assert result is False
    captured = capsys.readouterr()
    assert captured.out == ""


def test_check_overlap_detects_overlap_from_git(kb_repo: Path, capsys):
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active"
    (active / "branch-a").mkdir(parents=True)
    (active / "branch-b").mkdir(parents=True)

    run_git("checkout", "-b", "branch-a", cwd=kb_repo)
    (kb_repo / "shared.py").write_text("a = 1\n")
    run_git("add", "shared.py", cwd=kb_repo)
    run_git("commit", "-m", "a", cwd=kb_repo)

    run_git("checkout", "main", cwd=kb_repo)
    run_git("checkout", "-b", "branch-b", cwd=kb_repo)
    (kb_repo / "shared.py").write_text("b = 1\n")
    run_git("add", "shared.py", cwd=kb_repo)
    run_git("commit", "-m", "b", cwd=kb_repo)

    result = check_overlap("branch-a", kb_repo)
    assert result is True
    captured = capsys.readouterr()
    assert "branch-b" in captured.out
    assert "overlap" in captured.out.lower()


def test_check_overlap_no_overlap_returns_false(kb_repo: Path, capsys):
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active"
    (active / "branch-a").mkdir(parents=True)
    (active / "branch-b").mkdir(parents=True)

    run_git("checkout", "-b", "branch-a", cwd=kb_repo)
    (kb_repo / "a.py").write_text("a = 1\n")
    run_git("add", "a.py", cwd=kb_repo)
    run_git("commit", "-m", "a", cwd=kb_repo)

    run_git("checkout", "main", cwd=kb_repo)
    run_git("checkout", "-b", "branch-b", cwd=kb_repo)
    (kb_repo / "b.py").write_text("b = 1\n")
    run_git("add", "b.py", cwd=kb_repo)
    run_git("commit", "-m", "b", cwd=kb_repo)

    result = check_overlap("branch-a", kb_repo)
    assert result is False
    captured = capsys.readouterr()
    assert "no overlap" in captured.out.lower()


def test_overlap_line_positive_wording(kb_repo: Path):
    overlaps = [("branch-b", {"shared.py"}), ("branch-c", {"other.py"})]
    with patch("reinicorn.staging.overlapping_branches", return_value=overlaps):
        result = overlap_line("branch-a", kb_repo)
    assert result == "overlap: 2 branch(es) — see rcorn kb status"


def test_overlap_line_none_for_no_basis_and_empty(kb_repo: Path):
    with patch("reinicorn.staging.overlapping_branches", return_value=None):
        assert overlap_line("branch-a", kb_repo) == "overlap: none"
    with patch("reinicorn.staging.overlapping_branches", return_value=[]):
        assert overlap_line("branch-a", kb_repo) == "overlap: none"


def test_active_plan_names_sorted(kb_repo: Path):
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active"
    (active / "zeta").mkdir(parents=True)
    (active / "alpha").mkdir(parents=True)
    (active / "not-a-dir.md").write_text("x")
    assert active_branch_names(kb_repo / "kb", "testproject") == ["alpha", "zeta"]


def test_active_plan_names_missing_scope(kb_repo: Path):
    assert active_branch_names(kb_repo / "kb", "no-such-project") == []


def test_repo_kb_dir_creates_directory(kb_repo: Path):
    with patch("reinicorn.kb.kb_scope", return_value="myproject"):
        result = repo_kb_dir(kb_repo / "kb")
    assert result == kb_repo / "kb" / "myproject"
    assert result.is_dir()


def test_repo_kb_dir_is_idempotent(kb_repo: Path):
    with patch("reinicorn.kb.kb_scope", return_value="myproject"):
        first = repo_kb_dir(kb_repo / "kb")
        second = repo_kb_dir(kb_repo / "kb")
    assert first == second


def test_branch_changed_files_returns_diff_vs_main(kb_repo: Path):
    run_git("checkout", "-b", "feature-x", cwd=kb_repo)
    (kb_repo / "new.py").write_text("x = 1\n")
    run_git("add", "new.py", cwd=kb_repo)
    run_git("commit", "-m", "add new.py", cwd=kb_repo)

    result = branch_changed_files("feature-x", kb_repo)
    assert "new.py" in result


def test_branch_changed_files_returns_empty_on_main(kb_repo: Path):
    assert branch_changed_files("main", kb_repo) == set()


def test_branch_changed_files_returns_empty_for_missing_branch(kb_repo: Path):
    assert branch_changed_files("does-not-exist", kb_repo) == set()


def test_branch_changed_files_returns_empty_without_main(tmp_path: Path):
    """No main/master ref resolvable → return empty, never fabricate a base."""
    run_git("init", "-q", "-b", "wip", cwd=tmp_path)
    run_git(
        "-c", "user.email=t@t", "-c", "user.name=t", "commit",
        "--allow-empty", "-q", "-m", "init",
        cwd=tmp_path,
    )
    assert branch_changed_files("wip", tmp_path) == set()


def _detach(kb: Path) -> None:
    run_git("checkout", "-q", "--detach", "HEAD", cwd=kb)


def test_ensure_kb_on_main_fast_forwards_stale_local_main(kb_clone_repo, tmp_path):
    """From a detached HEAD, checkout main must not revert to a stale local main."""
    kb = kb_clone_repo / "kb"
    # Advance the remote past local main via a second clone
    other = tmp_path / "other"
    run_git("clone", "-q", str(tmp_path / "kb-remote"), str(other))
    run_git("config", "user.email", "t@t", cwd=other)
    run_git("config", "user.name", "T", cwd=other)
    (other / "README.md").write_text("# Kb v2\n")
    run_git("add", "-A", cwd=other)
    run_git("commit", "-q", "-m", "v2", cwd=other)
    run_git("push", "-q", "origin", "main", cwd=other)
    _detach(kb)

    assert ensure_kb_on_main(kb) is True
    assert (kb / "README.md").read_text() == "# Kb v2\n"  # not reverted to v1


def test_ensure_kb_on_main_reports_failed_checkout(kb_clone_repo):
    """A checkout that cannot land on main returns False instead of lying."""
    kb = kb_clone_repo / "kb"
    _detach(kb)
    # Uncommitted change conflicting with main blocks the checkout
    run_git("rm", "-q", "README.md", cwd=kb)
    (kb / "README.md").write_text("conflicting\n")
    run_git("add", "README.md", cwd=kb)
    run_git("commit", "-q", "-m", "detached edit", cwd=kb)
    (kb / "README.md").write_text("dirty\n")

    assert ensure_kb_on_main(kb) is False


def test_ensure_kb_on_main_reports_git_words_on_genuine_divergence(
    kb_clone_repo, tmp_path, capsys
):
    """A real ff-only failure surfaces git's own diagnosis via report_failure,
    not a hardcoded 'diverged' guess — golden principle 4, and the same
    single seam every other kb git failure goes through."""
    kb = kb_clone_repo / "kb"
    remote = tmp_path / "kb-remote"

    other = tmp_path / "other"
    run_git("clone", "-q", str(remote), str(other))
    run_git("config", "user.email", "t@t.com", cwd=other)
    run_git("config", "user.name", "T", cwd=other)
    (other / "remote.md").write_text("remote\n")
    run_git("add", "-A", cwd=other)
    run_git("commit", "-q", "-m", "remote", cwd=other)
    run_git("push", "-q", "origin", "main", cwd=other)

    (kb / "local.md").write_text("local\n")
    run_git("add", "-A", cwd=kb)
    run_git("commit", "-q", "-m", "local", cwd=kb)

    assert ensure_kb_on_main(kb) is False
    out = capsys.readouterr().out
    assert "Could not fast-forward kb main to origin/main" in out
    assert "git:" in out  # git's own stderr is reproduced, not a guessed cause
    assert "rcorn kb sync" in out


def test_commit_kb_refuses_off_main(kb_clone_repo, monkeypatch):
    """No commit lands on a detached HEAD — the work stays in the worktree."""
    kb = kb_clone_repo / "kb"
    _detach(kb)
    run_git("rm", "-q", "README.md", cwd=kb)
    run_git("commit", "-q", "-m", "conflict setup", cwd=kb)
    (kb / "README.md").write_text("draft\n")

    assert commit_kb(kb_clone_repo, "doc: draft", kb_dir=kb) is False
    r = run_git("log", "--oneline", "-1", cwd=kb)
    assert "doc: draft" not in r.stdout
    assert (kb / "README.md").read_text() == "draft\n"  # work intact
