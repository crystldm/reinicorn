"""Tests for rcorn feedback command."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from reinicorn.commands import feedback as feedback_cmds
from reinicorn.commands.feedback import (
    _EDITOR_TEMPLATE,
    _build_issue_body,
    _open_issue,
    _parse_editor_content,
    cmd_feedback,
)


def test_open_issue_targets_metadata_repo(monkeypatch):
    """The issue target is the package's own Repository URL — no hardcoded
    slug, so a fork/copy files feedback against itself automatically."""
    monkeypatch.setattr(feedback_cmds, "reinicorn_source_repo", lambda: "acme/reinicorn-fork")
    monkeypatch.setattr(feedback_cmds.shutil, "which", lambda _cmd: None)
    opened: list[str] = []
    monkeypatch.setattr(feedback_cmds, "_open_browser", opened.append)
    assert _open_issue("a title", "a body") == 0
    assert len(opened) == 1
    assert opened[0].startswith("https://github.com/acme/reinicorn-fork/issues/new?")


def test_open_issue_errors_when_repo_underivable(monkeypatch, capsys):
    monkeypatch.setattr(feedback_cmds, "reinicorn_source_repo", lambda: None)
    assert _open_issue("a title", "a body") == 1
    assert "repo" in capsys.readouterr().out.lower()


def test_build_issue_body_includes_version():
    body = _build_issue_body("Something is broken")
    assert "reinicorn" in body.lower()
    from reinicorn import __version__
    assert __version__ in body


def test_build_issue_body_includes_description():
    body = _build_issue_body("The hooks don't fire on checkout")
    assert "The hooks don't fire on checkout" in body


def test_feedback_inline_text():
    """feedback with inline text should not prompt for description."""
    with patch("reinicorn.commands.feedback._open_issue") as mock_open:
        mock_open.return_value = 0
        result = cmd_feedback("hooks aren't firing")
    assert result == 0
    mock_open.assert_called_once()
    title, _body = mock_open.call_args[0]
    assert "hooks" in title.lower()


def test_feedback_no_text_prompts(monkeypatch):
    """feedback with no text should prompt interactively."""
    monkeypatch.setattr("reinicorn.commands.feedback._read_from_editor", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt: "my bug report")
    with patch("reinicorn.commands.feedback._open_issue") as mock_open:
        mock_open.return_value = 0
        result = cmd_feedback(None)
    assert result == 0
    mock_open.assert_called_once()


def test_feedback_empty_input_returns_error(monkeypatch):
    """feedback with empty interactive input should fail."""
    monkeypatch.setattr("reinicorn.commands.feedback._read_from_editor", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    result = cmd_feedback(None)
    assert result == 1


def test_editor_template_has_comment_instructions():
    """Editor template should contain HTML-commented instructions."""
    assert "<!--" in _EDITOR_TEMPLATE
    assert "-->" in _EDITOR_TEMPLATE
    assert "title" in _EDITOR_TEMPLATE.lower()
    assert "body" in _EDITOR_TEMPLATE.lower() or "description" in _EDITOR_TEMPLATE.lower()


def test_parse_editor_content_strips_html_comments():
    """HTML comments should be stripped from editor content before parsing."""
    raw = "Fix the hooks\n<!-- this is a comment -->\n\nDetailed description here"
    title, desc = _parse_editor_content(raw)
    assert title == "Fix the hooks"
    assert "Detailed description here" in desc
    assert "comment" not in desc


def test_parse_editor_content_preserves_markdown_headers():
    """Markdown headers (# lines) should NOT be stripped — they're user content."""
    raw = "Bug title\n\n# Steps to reproduce\n1. Do the thing"
    title, desc = _parse_editor_content(raw)
    assert title == "Bug title"
    assert "# Steps to reproduce" in desc


def test_feedback_editor_path(monkeypatch):
    """feedback with no text, TTY, and EDITOR opens editor and uses content."""
    user_content = (
        "Bug: hooks crash\n"
        "<!-- This comment should be stripped -->\n"
        "\n"
        "# Steps to reproduce\n"
        "1. Run reinicorn\n"
        "2. See crash"
    )
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if len(cmd) >= 2 and cmd[0] == "vim" and str(cmd[-1]).endswith(".md"):
            path = cmd[-1]
            Path(path).write_text(user_content)
            return SimpleNamespace(returncode=0)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    with (
        patch("reinicorn.commands.feedback.subprocess.run", side_effect=fake_run),
        patch("reinicorn.commands.feedback._open_issue") as mock_open,
    ):
        mock_open.return_value = 0
        result = cmd_feedback(None)
    assert result == 0
    mock_open.assert_called_once()
    title, body = mock_open.call_args[0]
    assert "Bug: hooks crash" in title
    assert "# Steps to reproduce" in body
    assert "comment" not in body.lower()
