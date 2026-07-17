"""Tests for gh repo create integration in reins init."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.init import _detect_gh_status
from reinicorn.git import run_git


def test_detect_gh_status_not_installed():
    with patch("reinicorn.commands.init.gh_available", return_value=False):
        assert _detect_gh_status() == "not_installed"


def test_detect_gh_status_not_authed():
    with patch("reinicorn.commands.init.gh_available", return_value=True), \
         patch("reinicorn.commands.init.gh_authenticated", return_value=False):
        assert _detect_gh_status() == "not_authenticated"


def test_detect_gh_status_ready():
    with patch("reinicorn.commands.init.gh_available", return_value=True), \
         patch("reinicorn.commands.init.gh_authenticated", return_value=True):
        assert _detect_gh_status() == "ready"


def test_cli_create_remote_flag():
    from reinicorn.cli import main
    with patch("reinicorn.commands.init.cmd_init", return_value=0) as mock:
        main(["init", "--create-remote"])
    assert mock.call_args.kwargs["create_remote"] is True


def test_cli_kb_name_flag():
    from reinicorn.cli import main
    with patch("reinicorn.commands.init.cmd_init", return_value=0) as mock:
        main(["init", "--create-remote", "--kb-name", "custom-kb"])
    assert mock.call_args.kwargs["kb_name"] == "custom-kb"


def test_cli_rejects_local_and_create_remote():
    """--local and --create-remote are mutually exclusive."""
    from reinicorn.cli import main
    result = main(["init", "--local", "--create-remote"])
    assert result == 2


def test_cli_rejects_kb_url_and_create_remote():
    """--kb-url and --create-remote are mutually exclusive."""
    from reinicorn.cli import main
    result = main(["init", "--kb-url", "https://example.com", "--create-remote"])
    assert result == 2


def test_create_local_bare_uses_main_branch(tmp_path: Path):
    from reinicorn.commands.init import _create_local_bare
    target = tmp_path / "project"
    target.mkdir()
    bare_path = _create_local_bare(target)
    r = run_git("-C", bare_path, "symbolic-ref", "HEAD")
    assert r.stdout.strip() == "refs/heads/main"
