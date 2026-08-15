"""Tests for reins idea command."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from reinicorn import frontmatter as fm
from reinicorn.commands.doc_create import cmd_doc_create


def test_idea_creates_file(kb_repo: Path, capsys):
    with patch("reinicorn.commands.doc_create.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.doc_create.run_git") as mock_git, \
         patch("reinicorn.commands.doc_create.commit_kb") as mock_commit, \
         patch("reinicorn.commands.doc_create.kb_scope", return_value="reins"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_doc_create("idea", "my cool idea for testing")

    assert result == 0

    # Check the file was created
    ideas_dir = kb_repo / "kb" / "reins" / "ideas" / "test-user"
    assert ideas_dir.is_dir()
    files = list(ideas_dir.glob("*.md"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "my cool idea for testing" in content
    assert fm.get(content, "status") == "new"

    # Verify commit_kb was called, scoped to the created file (issue #35)
    mock_commit.assert_called_once()
    assert mock_commit.call_args[0][0] == kb_repo
    assert "my-cool-idea-for-testing" in mock_commit.call_args[0][1]
    assert mock_commit.call_args.kwargs["paths"] == files


def test_idea_empty_text_fails(capsys):
    result = cmd_doc_create("idea", "")
    assert result == 1


def test_idea_empty_whitespace_fails(capsys):
    result = cmd_doc_create("idea", "   ")
    assert result == 1


def test_idea_uses_repo_scoped_path(kb_repo: Path, capsys):
    with patch("reinicorn.commands.doc_create.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.doc_create.run_git") as mock_git, \
         patch("reinicorn.commands.doc_create.commit_kb"), \
         patch("reinicorn.commands.doc_create.kb_scope", return_value="myproject"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_doc_create("idea", "test repo scoping")

    assert result == 0
    ideas_dir = kb_repo / "kb" / "myproject" / "ideas" / "test-user"
    assert ideas_dir.is_dir()
    files = list(ideas_dir.glob("*.md"))
    assert len(files) == 1


def test_idea_filename_is_bare_slug(kb_repo: Path, capsys):
    """Filename follows the registry pattern ({slug}.md) so `idea show <slug>`
    resolves; the capture date lives in frontmatter, not the filename."""
    with patch("reinicorn.commands.doc_create.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.doc_create.run_git") as mock_git, \
         patch("reinicorn.commands.doc_create.commit_kb"), \
         patch("reinicorn.commands.doc_create.kb_scope", return_value="reins"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        assert cmd_doc_create("idea", "my cool idea for testing") == 0
        assert cmd_doc_create("idea", "my cool idea for testing") == 0  # collision

    ideas_dir = kb_repo / "kb" / "reins" / "ideas" / "test-user"
    assert (ideas_dir / "my-cool-idea-for-testing.md").is_file()
    assert (ideas_dir / "my-cool-idea-for-testing-2.md").is_file()
