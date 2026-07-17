"""Tests for rcorn plan create / plan status / plan complete."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.plan import cmd_plan_complete, cmd_plan_create, cmd_plan_status


def test_plan_create_on_feature_branch(kb_repo: Path, capsys):
    # Set up repo-scoped template directory
    tmpl_dir = kb_repo / "kb" / "testproject" / "exec-plans" / "_template"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    (tmpl_dir / "plan.md").write_text(
        "# Execution Plan: [Branch Name]\n\n"
        "**Author:** [developer or agent]\n"
        "**Date:** [date]\n"
        "**Ticket:** [TICKET-ID or N/A]\n"
        "**Status:** [planning | in-progress | complete | abandoned]\n\n"
        "## Goal\n\n## Acceptance Criteria\n\n## Tasks\n"
    )

    with patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.plan.current_branch", return_value="feature/PROJ-123-foo"), \
         patch("reinicorn.commands.plan.run_git") as mock_git, \
         patch("reinicorn.commands.plan.commit_kb") as mock_commit:
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_plan_create()

    assert result == 0
    # Branch name sanitized: feature/PROJ-123-foo → feature-PROJ-123-foo
    pdir = (
        kb_repo / "kb" / "testproject" / "exec-plans" / "active"
        / "feature-PROJ-123-foo"
    )
    assert pdir.is_dir()
    assert (pdir / "plan.md").is_file()

    # Check ticket extraction
    plan_content = (pdir / "plan.md").read_text()
    assert "PROJ-123" in plan_content

    captured = capsys.readouterr().out
    assert "PROJ-123" in captured

    # Verify commit_kb called
    mock_commit.assert_called_once()
    assert "feature/PROJ-123-foo" in mock_commit.call_args[0][1]


def test_plan_create_rejects_main_branch(kb_repo: Path, capsys):
    with patch("reinicorn.commands.plan.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.plan.current_branch", return_value="main"):
        result = cmd_plan_create()
    assert result == 1


def test_plan_create_rejects_detached_head(kb_repo: Path, capsys):
    with patch("reinicorn.commands.plan.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.plan.current_branch", return_value=""):
        result = cmd_plan_create()
    assert result == 1


def test_plan_create_already_exists(kb_repo: Path, capsys):
    # Sanitized dir name
    pdir = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-existing"
    pdir.mkdir(parents=True)
    (pdir / "plan.md").write_text("existing plan\n")

    with patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.plan.current_branch", return_value="feature/existing"):
        result = cmd_plan_create()

    assert result == 0
    assert "already exists" in capsys.readouterr().out.lower()


def test_plan_status_no_plan(kb_repo: Path, capsys):
    with patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.plan.current_branch", return_value="feature/no-plan"):
        result = cmd_plan_status()

    assert result == 0
    out = capsys.readouterr().out
    assert "no execution plan" in out.lower()
    assert "next: rcorn plan create" in out


def test_plan_status_shows_files(kb_repo: Path, capsys):
    # Sanitized dir name
    pdir = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-test"
    pdir.mkdir(parents=True)
    (pdir / "plan.md").write_text("# Plan\n\nContent here\n")

    with patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.plan.current_branch", return_value="feature/test"):
        result = cmd_plan_status()

    assert result == 0
    out = capsys.readouterr().out
    assert "plan.md" in out


def test_plan_complete_moves_to_completed(kb_repo: Path, capsys):
    # Sanitized dir name
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-done"
    active.mkdir(parents=True)
    (active / "plan.md").write_text("# Plan\n\n**Status:** in-progress\n")

    with patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.plan.commit_kb") as mock_commit:
        result = cmd_plan_complete("feature/done")

    assert result == 0
    assert not active.is_dir()
    completed = (
        kb_repo / "kb" / "testproject" / "exec-plans" / "completed" / "feature-done"
    )
    assert completed.is_dir()
    assert "complete" in (completed / "plan.md").read_text()

    # Verify commit_kb called
    mock_commit.assert_called_once()
    assert "feature/done" in mock_commit.call_args[0][1]


def test_plan_complete_updates_status(kb_repo: Path, capsys):
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-x"
    active.mkdir(parents=True)
    (active / "plan.md").write_text("# Plan\n\n**Status:** planning\n")

    with patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.plan.commit_kb"):
        cmd_plan_complete("feature/x")

    completed = kb_repo / "kb" / "testproject" / "exec-plans" / "completed" / "feature-x"
    content = (completed / "plan.md").read_text()
    assert "**Status:** complete" in content


def test_plan_complete_missing_plan(kb_repo: Path, capsys):
    with patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.repo_root", return_value=kb_repo):
        result = cmd_plan_complete("feature/nonexistent")

    assert result == 1
    assert "no active plan" in capsys.readouterr().out.lower()


def test_plan_complete_defaults_to_current_branch(kb_repo: Path, capsys):
    active = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-cur"
    active.mkdir(parents=True)
    (active / "plan.md").write_text("# Plan\n\n**Status:** in-progress\n")

    with patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.plan.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.plan.current_branch", return_value="feature/cur"), \
         patch("reinicorn.commands.plan.commit_kb"):
        result = cmd_plan_complete()

    assert result == 0
    assert not active.is_dir()
    completed = (
        kb_repo / "kb" / "testproject" / "exec-plans" / "completed" / "feature-cur"
    )
    assert completed.is_dir()
