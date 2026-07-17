"""Tests for reinicorn.mode."""

from __future__ import annotations

from pathlib import Path

from reinicorn.git import run_git
from reinicorn.mode import can_publish, get_mode, hook_check, set_mode


def test_project_gitignore_keeps_mode_local_and_manifest_trackable(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    (tmp_path / ".gitignore").write_text((project_root / ".gitignore").read_text())
    state_dir = tmp_path / ".reinicorn"
    state_dir.mkdir()
    (state_dir / "mode").write_text("disabled\n")
    (state_dir / "manifest.json").write_text("{}\n")
    run_git("init", "-q", cwd=tmp_path)

    def is_ignored(path: str) -> bool:
        result = run_git(
            "-c",
            "core.excludesFile=/dev/null",
            "check-ignore",
            "--quiet",
            "--no-index",
            path,
            cwd=tmp_path,
            check=False,
        )
        assert result.returncode in (0, 1), result.stderr
        return result.returncode == 0

    assert is_ignored(".reinicorn/mode")
    assert not is_ignored(".reinicorn/manifest.json")


def test_default_mode_when_no_file(tmp_path: Path):
    assert get_mode(tmp_path) == "enabled"


def test_set_and_get_mode(tmp_path: Path):
    set_mode("disabled", tmp_path)
    assert get_mode(tmp_path) == "disabled"

    set_mode("incognito", tmp_path)
    assert get_mode(tmp_path) == "incognito"
    assert (tmp_path / ".reinicorn" / "mode").read_text() == "incognito\n"

    set_mode("enabled", tmp_path)
    assert get_mode(tmp_path) == "enabled"


def test_hook_check_enabled(tmp_path: Path):
    set_mode("enabled", tmp_path)
    assert hook_check(tmp_path) is True


def test_hook_check_disabled(tmp_path: Path):
    set_mode("disabled", tmp_path)
    assert hook_check(tmp_path) is False


def test_hook_check_incognito(tmp_path: Path):
    set_mode("incognito", tmp_path)
    assert hook_check(tmp_path) is True


def test_can_publish_enabled(tmp_path: Path):
    set_mode("enabled", tmp_path)
    assert can_publish(tmp_path) is True


def test_can_publish_disabled(tmp_path: Path):
    set_mode("disabled", tmp_path)
    assert can_publish(tmp_path) is False


def test_can_publish_incognito(tmp_path: Path):
    set_mode("incognito", tmp_path)
    assert can_publish(tmp_path) is False


def test_cmd_mode_status_prints_current_mode(capsys):
    from unittest.mock import patch

    from reinicorn.commands.mode_cmds import cmd_mode_status
    with patch("reinicorn.commands.mode_cmds.get_mode", return_value="enabled"):
        result = cmd_mode_status()
    assert result == 0
    captured = capsys.readouterr().out
    assert "enabled" in captured.lower()


def test_cmd_incognito_sets_incognito_when_enabled():
    from unittest.mock import patch

    from reinicorn.commands.mode_cmds import cmd_incognito
    with patch("reinicorn.commands.mode_cmds.get_mode", return_value="enabled"), \
         patch("reinicorn.commands.mode_cmds.set_mode") as mock_set:
        result = cmd_incognito()
    assert result == 0
    mock_set.assert_called_once_with("incognito")


def test_enable_twice_is_explicit_noop(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    from reinicorn.commands.mode_cmds import cmd_disable, cmd_enable
    # Real transition first (default mode is "enabled", so exercise set_mode)
    assert cmd_disable() == 0
    assert cmd_enable() == 0
    assert get_mode(kb_repo) == "enabled"
    capsys.readouterr()
    assert cmd_enable() == 0
    out = capsys.readouterr().out
    assert "(no-op)" in out
    assert "already enabled" in out


def test_disable_noop_suggests_enable(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    from reinicorn.commands.mode_cmds import cmd_disable
    assert cmd_disable() == 0
    capsys.readouterr()
    assert cmd_disable() == 0
    out = capsys.readouterr().out
    assert "(no-op)" in out
    assert "next: rcorn mode enable" in out


def test_cmd_incognito_is_idempotent_when_already_incognito():
    """Running incognito while already incognito must NOT toggle back to enabled."""
    from unittest.mock import patch

    from reinicorn.commands.mode_cmds import cmd_incognito
    with patch("reinicorn.commands.mode_cmds.get_mode", return_value="incognito"), \
         patch("reinicorn.commands.mode_cmds.set_mode") as mock_set:
        result = cmd_incognito()
    assert result == 0
    mock_set.assert_not_called()
