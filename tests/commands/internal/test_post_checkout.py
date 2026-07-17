"""Tests for rcorn _post-checkout — submodule init + new-branch suggestion."""

from __future__ import annotations

from pathlib import Path

from reinicorn.commands.internal.post_checkout import cmd_post_checkout
from reinicorn.git import run_git


def test_file_checkout_is_noop(submodule_repo: Path, monkeypatch, capsys):
    """checkout_type '0' (file checkout) → exit 0, no output."""
    monkeypatch.chdir(submodule_repo)
    assert cmd_post_checkout(["a", "b", "0"]) == 0
    assert capsys.readouterr().out == ""


def test_disabled_mode_is_noop(submodule_repo: Path, monkeypatch, capsys):
    """Disabled mode → no suggestion printed."""
    state_dir = submodule_repo / ".reinicorn"
    state_dir.mkdir()
    (state_dir / "mode").write_text("disabled")
    monkeypatch.chdir(submodule_repo)
    assert cmd_post_checkout(["a", "b", "1"]) == 0
    assert capsys.readouterr().out == ""


def test_new_branch_suggests_plan_create(submodule_repo: Path, monkeypatch, capsys):
    """New branch without upstream → suggests 'rcorn plan create'."""
    run_git("checkout", "-q", "-b", "feature-new-thing", cwd=submodule_repo)
    monkeypatch.chdir(submodule_repo)
    assert cmd_post_checkout(["a", "b", "1"]) == 0
    out = capsys.readouterr().out
    assert "feature-new-thing" in out
    assert "rcorn plan create" in out
    assert "/create-exec-plan" not in out


def test_ticket_id_detected_in_branch(submodule_repo: Path, monkeypatch, capsys):
    """Branch containing a JIRA-style ticket id → id shown in suggestion."""
    run_git("checkout", "-q", "-b", "feature/ABC-123-do-thing", cwd=submodule_repo)
    monkeypatch.chdir(submodule_repo)
    assert cmd_post_checkout(["a", "b", "1"]) == 0
    out = capsys.readouterr().out
    assert "ABC-123" in out
    assert "rcorn plan create" in out
