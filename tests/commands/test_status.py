"""Tests for reins kb status command."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.status import cmd_status
from tests.conftest import doc_text


def test_status_shows_layout_and_branch(kb_repo: Path, capsys):
    with patch("reinicorn.commands.status.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.status.current_branch", return_value="main"), \
         patch("reinicorn.commands.status.run_git") as mock_git:
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="0\n"
        )
        result = cmd_status()

    assert result == 0
    out = capsys.readouterr().out
    assert "kb" in out.lower()
    assert "main" in out


def test_status_shows_in_review_section(kb_repo: Path, capsys):
    d = kb_repo / "kb" / "testproject" / "specs" / "drafts"
    d.mkdir(parents=True)
    (d / "hot.md").write_text(doc_text(
        title="hot", slug="hot", author="tester", status="in-review",
        review_pr="https://github.com/owner/kb/pull/3",
        body="\n# hot\n\nbody\n",
    ))
    with patch("reinicorn.commands.status.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.status.current_branch", return_value="main"), \
         patch("reinicorn.commands.status.run_git") as mock_git:
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="0\n"
        )
        result = cmd_status()

    assert result == 0
    out = capsys.readouterr().out
    assert "In review" in out
    assert "hot" in out
    assert "pull/3" in out


def test_status_no_drafts_no_review_section(kb_repo: Path, capsys):
    with patch("reinicorn.commands.status.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.status.current_branch", return_value="main"), \
         patch("reinicorn.commands.status.run_git") as mock_git:
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="0\n"
        )
        result = cmd_status()

    assert result == 0
    out = capsys.readouterr().out
    assert "In review" not in out


