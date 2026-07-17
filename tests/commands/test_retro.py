"""Tests for retro create/show/complete-warning lifecycle."""

from __future__ import annotations

from pathlib import Path

from reinicorn.commands.doc_create import cmd_retro_create
from reinicorn.commands.plan import cmd_plan_complete
from reinicorn.git import run_git


def _setup_branch_with_plan(repo: Path, branch: str) -> Path:
    run_git("checkout", "-q", "-b", branch, cwd=repo)
    active = repo / "kb" / "unknown" / "exec-plans" / "active" / branch
    active.mkdir(parents=True)
    (active / "plan.md").write_text(
        f"# Execution Plan: {branch}\n\n**Status:** in-progress\n"
    )
    return active


def test_retro_create_targets_active_plan_dir(submodule_repo: Path, monkeypatch):
    active = _setup_branch_with_plan(submodule_repo, "feature-r")
    monkeypatch.chdir(submodule_repo)
    assert cmd_retro_create() == 0
    retro = active / "retro.md"
    assert retro.is_file()
    text = retro.read_text()
    for section in ("What Went Well", "What Could Be Improved", "Lessons Learned", "Action Items"):
        assert f"## {section}" in text


def test_retro_create_without_plan_uses_completed_dir(submodule_repo: Path, monkeypatch):
    run_git("checkout", "-q", "-b", "feature-noplan", cwd=submodule_repo)
    monkeypatch.chdir(submodule_repo)
    assert cmd_retro_create() == 0
    completed = submodule_repo / "kb" / "unknown" / "exec-plans" / "completed"
    assert (completed / "feature-noplan" / "retro.md").is_file()


def test_plan_complete_warns_on_empty_retro(submodule_repo: Path, monkeypatch, capsys):
    _setup_branch_with_plan(submodule_repo, "feature-empty-retro")
    monkeypatch.chdir(submodule_repo)
    cmd_retro_create()
    capsys.readouterr()  # discard create output
    assert cmd_plan_complete() == 0
    out = capsys.readouterr().out
    assert "retro" in out.lower()
    assert "rcorn retro create" in out


def test_plan_complete_quiet_on_filled_retro(submodule_repo: Path, monkeypatch, capsys):
    active = _setup_branch_with_plan(submodule_repo, "feature-good-retro")
    monkeypatch.chdir(submodule_repo)
    cmd_retro_create()
    retro = active / "retro.md"
    retro.write_text(
        retro.read_text().replace(
            "## What Went Well\n\n- ", "## What Went Well\n\n- Shipped it cleanly"
        )
    )
    capsys.readouterr()
    assert cmd_plan_complete() == 0
    out = capsys.readouterr().out
    assert "No retro captured" not in out
    # retro traveled with the plan dir
    completed = submodule_repo / "kb" / "unknown" / "exec-plans" / "completed"
    assert (completed / "feature-good-retro" / "retro.md").is_file()
