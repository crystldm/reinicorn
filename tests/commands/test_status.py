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




# --- hook health and pointer drift (issue #24) ---


def test_status_reports_stale_hook(submodule_repo: Path, capsys):
    """A reins-era hook is a silently dead guard — status must surface it."""
    hooks = submodule_repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-push").write_text(
        "#!/usr/bin/env bash\n"
        "if command -v reins &>/dev/null; then\n"
        "    reins _pre-push\n"
        "    exit $?\n"
        "fi\n"
        "\n"
        "exit 0\n"
    )

    with patch("reinicorn.commands.status.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.status.current_branch", return_value="main"):
        result = cmd_status()

    assert result == 0
    out = capsys.readouterr().out
    assert "pre-push" in out
    assert "stale" in out
    assert "rcorn hooks install" in out


def test_status_reports_unreachable_marker(submodule_repo: Path, capsys):
    """A hook whose reinicorn marker sits after an unconditional exit is a
    dead guard — status must surface it."""
    from reinicorn.hooks_health import MARKER

    hooks = submodule_repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "post-merge").write_text(
        f"#!/bin/sh\necho other-tool\nexit 0\n\n{MARKER}\n\nrcorn _post-merge\n"
    )

    with patch("reinicorn.commands.status.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.status.current_branch", return_value="main"):
        result = cmd_status()

    assert result == 0
    out = capsys.readouterr().out
    assert "post-merge" in out
    assert "unreachable" in out


def test_status_reports_pointer_behind_kb_remote(submodule_repo: Path, capsys):
    """Parent pointer behind kb origin/main is drift that otherwise only
    surfaces in CI (carried over from #21)."""
    from reinicorn.git import run_git

    kb = submodule_repo / "kb"
    (kb / "new.md").write_text("# new\n")
    run_git("add", "-A", cwd=kb)
    run_git("commit", "-q", "-m", "ahead of parent pointer", cwd=kb)
    run_git(
        "-c", "protocol.file.allow=always",
        "push", "-q", "origin", "main", cwd=kb,
    )

    with patch("reinicorn.commands.status.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.status.current_branch", return_value="main"):
        result = cmd_status()

    assert result == 0
    out = capsys.readouterr().out
    assert "behind" in out
    assert "1 commit" in out


def test_status_healthy_hooks_and_pointer_stay_quiet(submodule_repo: Path, capsys):
    """No hook warnings and no drift warning when everything is current."""
    hooks = submodule_repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-push").write_text(
        "#!/usr/bin/env bash\n"
        "if command -v rcorn &>/dev/null; then\n"
        "    rcorn _pre-push\n"
        "    exit $?\n"
        "fi\n"
        "\n"
        "exit 0\n"
    )

    with patch("reinicorn.commands.status.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.status.current_branch", return_value="main"):
        result = cmd_status()

    assert result == 0
    out = capsys.readouterr().out
    assert "Hook " not in out
    assert "behind" not in out
