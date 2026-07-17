"""Tests for reinicorn.kb."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from reinicorn.git import run_git
from reinicorn.kb import (
    _parse_kb_submodule_path,
    active_plan_names,
    branch_changed_files,
    check_overlap,
    get_kb_dir,
    overlap_line,
    plan_dir,
    repo_kb_dir,
    require_kb_dir,
)


def test_parse_kb_submodule_path_standard():
    text = '[submodule "kb"]\n    path = kb\n    url = fake\n'
    assert _parse_kb_submodule_path(text) == "kb"


def test_parse_kb_submodule_path_custom_dir():
    text = '[submodule "kb"]\n    path = tools/kb\n    url = fake\n'
    assert _parse_kb_submodule_path(text) == "tools/kb"


def test_parse_kb_submodule_path_no_kb_section():
    text = '[submodule "other"]\n    path = other\n    url = fake\n'
    assert _parse_kb_submodule_path(text) is None


def test_parse_kb_submodule_path_empty():
    assert _parse_kb_submodule_path("") is None


def test_parse_kb_submodule_path_blank_value():
    # A blank path= value must not resolve to the repo root.
    text = '[submodule "kb"]\n    path = \n    url = fake\n'
    assert _parse_kb_submodule_path(text) is None


def test_parse_kb_submodule_path_does_not_match_pathname():
    # "pathname" key must not be confused with "path"
    text = '[submodule "kb"]\n    pathname = wrong\n    path = correct\n'
    assert _parse_kb_submodule_path(text) == "correct"


def test_parse_kb_submodule_path_url_contains_kb():
    # A URL with "kb" in it must not trigger a false positive
    text = (
        '[submodule "other"]\n    path = other\n'
        "    url = git@github.com:org/kb-tools.git\n"
    )
    assert _parse_kb_submodule_path(text) is None


def test_get_kb_dir_returns_path(kb_repo: Path):
    assert get_kb_dir(kb_repo) == kb_repo / "kb"


def test_get_kb_dir_returns_none_when_absent(tmp_path: Path):
    assert get_kb_dir(tmp_path) is None


def test_get_kb_dir_rejects_traversal_path(tmp_path: Path, capsys):
    """A .gitmodules path that escapes the repo root is refused."""
    (tmp_path / ".gitmodules").write_text(
        '[submodule "kb"]\n    path = ../escape\n    url = fake\n'
    )
    assert get_kb_dir(tmp_path) is None
    assert "Refusing kb submodule path" in capsys.readouterr().out


def test_get_kb_dir_rejects_absolute_path(tmp_path: Path):
    """An absolute .gitmodules path is refused (would resolve outside root)."""
    (tmp_path / ".gitmodules").write_text(
        '[submodule "kb"]\n    path = /etc\n    url = fake\n'
    )
    assert get_kb_dir(tmp_path) is None


def test_require_kb_dir_raises_when_none(tmp_path: Path):
    with pytest.raises(SystemExit):
        require_kb_dir(tmp_path)


def test_require_kb_dir_returns_path(kb_repo: Path):
    result = require_kb_dir(kb_repo)
    assert isinstance(result, Path)
    assert result == kb_repo / "kb"


def test_plan_dir(kb_repo: Path):
    with patch("reinicorn.kb.kb_scope", return_value="testproject"):
        result = plan_dir(kb_repo / "kb", "feature/foo")
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
    with patch("reinicorn.kb.overlapping_branches", return_value=overlaps):
        result = overlap_line("branch-a", kb_repo)
    assert result == "overlap: 2 branch(es) — see rcorn kb status"


def test_overlap_line_none_for_no_basis_and_empty(kb_repo: Path):
    with patch("reinicorn.kb.overlapping_branches", return_value=None):
        assert overlap_line("branch-a", kb_repo) == "overlap: none"
    with patch("reinicorn.kb.overlapping_branches", return_value=[]):
        assert overlap_line("branch-a", kb_repo) == "overlap: none"


def test_active_plan_names_sorted(kb_repo: Path):
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active"
    (active / "zeta").mkdir(parents=True)
    (active / "alpha").mkdir(parents=True)
    (active / "not-a-dir.md").write_text("x")
    assert active_plan_names(kb_repo / "kb", "testproject") == ["alpha", "zeta"]


def test_active_plan_names_missing_scope(kb_repo: Path):
    assert active_plan_names(kb_repo / "kb", "no-such-project") == []


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
