"""Tests for mode commands: enable, disable, incognito."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.mode_cmds import cmd_disable, cmd_enable, cmd_incognito
from reinicorn.mode import get_mode


def test_enable(kb_repo: Path, capsys):
    with patch("reinicorn.mode.repo_root", return_value=kb_repo):
        assert cmd_enable() == 0
        assert get_mode(kb_repo) == "enabled"
    assert "enabled" in capsys.readouterr().out.lower()


def test_disable(kb_repo: Path, capsys):
    with patch("reinicorn.mode.repo_root", return_value=kb_repo):
        assert cmd_disable() == 0
        assert get_mode(kb_repo) == "disabled"
    assert "disabled" in capsys.readouterr().out.lower()


def test_incognito_enter(kb_repo: Path, capsys):
    with patch("reinicorn.mode.repo_root", return_value=kb_repo):
        assert cmd_incognito() == 0
        assert get_mode(kb_repo) == "incognito"
    assert "incognito" in capsys.readouterr().out.lower()


def test_incognito_is_idempotent(kb_repo: Path, capsys):
    """Running incognito while already incognito stays incognito (no toggle off)."""
    with patch("reinicorn.mode.repo_root", return_value=kb_repo):
        from reinicorn.mode import set_mode
        set_mode("incognito", kb_repo)
        assert cmd_incognito() == 0
        assert get_mode(kb_repo) == "incognito"
    assert "already" in capsys.readouterr().out.lower()
