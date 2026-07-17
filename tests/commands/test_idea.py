"""Tests for reins idea command."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.idea import cmd_idea


def test_idea_creates_file(kb_repo: Path, capsys):
    with patch("reinicorn.commands.idea.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.idea.run_git") as mock_git, \
         patch("reinicorn.commands.idea.commit_kb") as mock_commit, \
         patch("reinicorn.commands.idea.kb_scope", return_value="reins"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_idea("my cool idea for testing")

    assert result == 0

    # Check the file was created
    ideas_dir = kb_repo / "kb" / "reins" / "ideas" / "test-user"
    assert ideas_dir.is_dir()
    files = list(ideas_dir.glob("*.md"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "my cool idea for testing" in content
    assert "**Status:** new" in content

    # Verify commit_kb was called
    mock_commit.assert_called_once()
    assert mock_commit.call_args[0][0] == kb_repo
    assert "my-cool-idea-for-testing" in mock_commit.call_args[0][1]


def test_idea_empty_text_fails(capsys):
    result = cmd_idea("")
    assert result == 1


def test_idea_empty_whitespace_fails(capsys):
    result = cmd_idea("   ")
    assert result == 1


def test_idea_uses_repo_scoped_path(kb_repo: Path, capsys):
    with patch("reinicorn.commands.idea.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.idea.run_git") as mock_git, \
         patch("reinicorn.commands.idea.commit_kb"), \
         patch("reinicorn.commands.idea.kb_scope", return_value="myproject"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_idea("test repo scoping")

    assert result == 0
    ideas_dir = kb_repo / "kb" / "myproject" / "ideas" / "test-user"
    assert ideas_dir.is_dir()
    files = list(ideas_dir.glob("*.md"))
    assert len(files) == 1


def test_idea_filename_is_bare_slug(kb_repo: Path, capsys):
    """Filename follows the registry pattern ({slug}.md) so `idea show <slug>`
    resolves; the capture date lives in frontmatter, not the filename."""
    with patch("reinicorn.commands.idea.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.idea.run_git") as mock_git, \
         patch("reinicorn.commands.idea.commit_kb"), \
         patch("reinicorn.commands.idea.kb_scope", return_value="reins"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        assert cmd_idea("my cool idea for testing") == 0
        assert cmd_idea("my cool idea for testing") == 0  # collision

    ideas_dir = kb_repo / "kb" / "reins" / "ideas" / "test-user"
    assert (ideas_dir / "my-cool-idea-for-testing.md").is_file()
    assert (ideas_dir / "my-cool-idea-for-testing-2.md").is_file()
