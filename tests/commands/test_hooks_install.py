"""Tests for Reinicorn hooks install command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.hooks_install import (
    HOOK_NAMES,
    MARKER,
    _merge_claude_settings,
    _merge_copilot_settings,
    _merge_cursor_settings,
    cmd_hooks_install,
)


def test_hooks_install_new(kb_repo: Path, capsys):
    # Create hooks source
    hooks_src = kb_repo / "hooks"
    hooks_src.mkdir(exist_ok=True)
    for name in HOOK_NAMES:
        (hooks_src / name).write_text(f"#!/usr/bin/env bash\n# {name}\n")

    git_dir = kb_repo / ".git"
    hooks_dest = git_dir / "hooks"

    with patch("reinicorn.commands.hooks_install.run_git") as mock_git, \
         patch("reinicorn.commands.hooks_install.reinicorn_root", return_value=kb_repo):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=str(git_dir) + "\n"
        )
        result = cmd_hooks_install()

    assert result == 0
    for name in HOOK_NAMES:
        assert (hooks_dest / name).is_file()

    out = capsys.readouterr().out
    assert "INSTALLED" in out


def test_hooks_install_idempotent(kb_repo: Path, capsys):
    hooks_src = kb_repo / "hooks"
    hooks_src.mkdir(exist_ok=True)
    for name in HOOK_NAMES:
        (hooks_src / name).write_text(f"#!/usr/bin/env bash\n# {name}\n")

    git_dir = kb_repo / ".git"
    hooks_dest = git_dir / "hooks"
    hooks_dest.mkdir(parents=True, exist_ok=True)

    # Pre-install with marker
    for name in HOOK_NAMES:
        (hooks_dest / name).write_text(f"#!/usr/bin/env bash\nexisting\n{MARKER}\n# reinicorn\n")

    with patch("reinicorn.commands.hooks_install.run_git") as mock_git, \
         patch("reinicorn.commands.hooks_install.reinicorn_root", return_value=kb_repo):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=str(git_dir) + "\n"
        )
        result = cmd_hooks_install()

    assert result == 0
    out = capsys.readouterr().out
    assert "already installed" in out.lower()


def test_hooks_install_idempotent_prints_noop(kb_repo: Path, capsys):
    """Marker-skipped reinstall reports an explicit (no-op)."""
    hooks_src = kb_repo / "hooks"
    hooks_src.mkdir(exist_ok=True)
    for name in HOOK_NAMES:
        (hooks_src / name).write_text(f"#!/usr/bin/env bash\n# {name}\n")

    git_dir = kb_repo / ".git"
    hooks_dest = git_dir / "hooks"
    hooks_dest.mkdir(parents=True, exist_ok=True)
    for name in HOOK_NAMES:
        (hooks_dest / name).write_text(f"#!/usr/bin/env bash\nexisting\n{MARKER}\n# reinicorn\n")

    with patch("reinicorn.commands.hooks_install.run_git") as mock_git, \
         patch("reinicorn.commands.hooks_install.reinicorn_root", return_value=kb_repo):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=str(git_dir) + "\n"
        )
        result = cmd_hooks_install()

    assert result == 0
    assert "(no-op)" in capsys.readouterr().out


def test_hooks_install_missing_sources_is_not_noop(kb_repo: Path, capsys):
    """Skips caused by missing source files must NOT claim 'already installed'."""
    hooks_src = kb_repo / "hooks"
    hooks_src.mkdir(exist_ok=True)  # dir exists but has no hook files

    git_dir = kb_repo / ".git"

    with patch("reinicorn.commands.hooks_install.run_git") as mock_git, \
         patch("reinicorn.commands.hooks_install.reinicorn_root", return_value=kb_repo):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=str(git_dir) + "\n"
        )
        result = cmd_hooks_install()

    assert result == 0
    assert "(no-op)" not in capsys.readouterr().out


# --- stale-hook repair and append safety (issue #24) ---


_REINS_HOOK = (
    "#!/usr/bin/env bash\n"
    "if command -v reins &>/dev/null; then\n"
    "    reins _pre-push\n"
    "    exit $?\n"
    "fi\n"
    "\n"
    "exit 0\n"
)


def _run_install(kb_repo: Path) -> int:
    git_dir = kb_repo / ".git"
    with patch("reinicorn.commands.hooks_install.run_git") as mock_git, \
         patch("reinicorn.commands.hooks_install.reinicorn_root", return_value=kb_repo):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=str(git_dir) + "\n"
        )
        return cmd_hooks_install()


def _seed_sources(kb_repo: Path) -> None:
    hooks_src = kb_repo / "hooks"
    hooks_src.mkdir(exist_ok=True)
    for name in HOOK_NAMES:
        (hooks_src / name).write_text(
            f"#!/usr/bin/env bash\nrcorn _{name}\nexit $?\n"
        )


def test_hooks_install_replaces_stale_reins_hook(kb_repo: Path, capsys):
    """A reins-era hook is stale, not foreign — overwrite it with the
    current hook instead of appending after its unconditional exit."""
    _seed_sources(kb_repo)
    hooks_dest = kb_repo / ".git" / "hooks"
    hooks_dest.mkdir(parents=True, exist_ok=True)
    for name in HOOK_NAMES:
        (hooks_dest / name).write_text(_REINS_HOOK)

    result = _run_install(kb_repo)

    assert result == 0
    out = capsys.readouterr().out
    assert "REPLACED" in out
    for name in HOOK_NAMES:
        text = (hooks_dest / name).read_text()
        assert "reins " not in text
        assert f"rcorn _{name}" in text


def test_hooks_install_replaces_stale_hook_with_dead_append(kb_repo: Path, capsys):
    """A reins hook that already got the old broken append (marker after
    exit 0) is repaired by replacement, not skipped for carrying the marker."""
    _seed_sources(kb_repo)
    hooks_dest = kb_repo / ".git" / "hooks"
    hooks_dest.mkdir(parents=True, exist_ok=True)
    damaged = _REINS_HOOK + f"\n{MARKER}\n\nrcorn _pre-push\nexit $?\n"
    (hooks_dest / "pre-push").write_text(damaged)

    result = _run_install(kb_repo)

    assert result == 0
    assert "REPLACED" in capsys.readouterr().out
    text = (hooks_dest / "pre-push").read_text()
    assert "reins " not in text
    assert "rcorn _pre-push" in text


def test_hooks_install_refuses_append_after_unconditional_exit(kb_repo: Path, capsys):
    """Appending after a foreign hook's unconditional exit would be
    unreachable — refuse loudly, never report success."""
    _seed_sources(kb_repo)
    hooks_dest = kb_repo / ".git" / "hooks"
    hooks_dest.mkdir(parents=True, exist_ok=True)
    foreign = "#!/bin/sh\necho other-tool\nexit 0\n"
    (hooks_dest / "pre-push").write_text(foreign)

    result = _run_install(kb_repo)

    assert result == 1
    out = capsys.readouterr().out
    assert "APPENDED: pre-push" not in out
    assert "FAILED: pre-push" in out
    # File untouched — no dead content appended
    assert (hooks_dest / "pre-push").read_text() == foreign


def test_hooks_install_appends_to_fall_through_hook(kb_repo: Path, capsys):
    """A foreign hook that can fall through still gets the chained append."""
    _seed_sources(kb_repo)
    hooks_dest = kb_repo / ".git" / "hooks"
    hooks_dest.mkdir(parents=True, exist_ok=True)
    foreign = "#!/bin/sh\necho other-tool\n"
    (hooks_dest / "pre-push").write_text(foreign)

    result = _run_install(kb_repo)

    assert result == 0
    assert "APPENDED: pre-push" in capsys.readouterr().out
    text = (hooks_dest / "pre-push").read_text()
    assert text.startswith(foreign)
    assert MARKER in text
    assert "rcorn _pre-push" in text


def test_hooks_install_rerun_over_verbatim_copy_is_noop(kb_repo: Path, capsys):
    """A fresh install copies the template verbatim (no marker); re-running
    must recognize it as already installed, not refuse it as a foreign hook
    ending in an unconditional exit."""
    _seed_sources(kb_repo)

    assert _run_install(kb_repo) == 0
    capsys.readouterr()
    result = _run_install(kb_repo)

    assert result == 0
    out = capsys.readouterr().out
    assert "FAILED" not in out
    assert "already installed" in out


# --- _merge_claude_settings tests ---


def _claude_entry(cmd: str = ".claude/hooks/enforce-doc-templates.sh") -> dict:
    return {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": cmd}]}


def test_merge_claude_settings_creates_new_file(tmp_path: Path):
    settings_path = tmp_path / ".claude" / "settings.json"
    entries = [_claude_entry()]

    _merge_claude_settings(settings_path, entries)

    assert settings_path.is_file()
    settings = json.loads(settings_path.read_text())
    assert settings["hooks"]["PreToolUse"] == entries


def test_merge_claude_settings_preserves_existing_config(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({
        "permissions": {"allow": ["Read"]},
        "hooks": {"PostToolUse": [{"command": "echo done"}]},
    }))

    entries = [_claude_entry()]
    _merge_claude_settings(settings_path, entries)

    settings = json.loads(settings_path.read_text())
    assert settings["permissions"]["allow"] == ["Read"]
    assert settings["hooks"]["PostToolUse"] == [{"command": "echo done"}]
    assert settings["hooks"]["PreToolUse"] == entries


def test_merge_claude_settings_idempotent(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    entries = [_claude_entry()]

    _merge_claude_settings(settings_path, entries)
    _merge_claude_settings(settings_path, entries)

    settings = json.loads(settings_path.read_text())
    assert len(settings["hooks"]["PreToolUse"]) == 1



def test_merge_claude_settings_handles_corrupt_json(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{not valid json")

    entries = [_claude_entry()]
    _merge_claude_settings(settings_path, entries)

    settings = json.loads(settings_path.read_text())
    assert settings["hooks"]["PreToolUse"] == entries


# --- Claude Code hooks installation ---


def test_hooks_install_copies_editor_hooks(kb_repo: Path):
    """Full cmd_hooks_install installs git hooks and all editor hooks."""
    # Create git hooks source
    hooks_src = kb_repo / "hooks"
    hooks_src.mkdir(exist_ok=True)
    for name in HOOK_NAMES:
        (hooks_src / name).write_text(f"#!/usr/bin/env bash\n# {name}\n")

    # Create editor hooks source
    editor_hooks_src = kb_repo / "editor-hooks"
    editor_hooks_src.mkdir(exist_ok=True)
    (editor_hooks_src / "enforce-doc-templates.sh").write_text(
        '#!/usr/bin/env bash\nrcorn _check-path "$FILE"\n'
    )

    git_dir = kb_repo / ".git"

    with patch("reinicorn.commands.hooks_install.run_git") as mock_git, \
         patch("reinicorn.commands.hooks_install.reinicorn_root", return_value=kb_repo), \
         patch("reinicorn.commands.hooks_install.repo_root", return_value=kb_repo):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=str(git_dir) + "\n"
        )
        result = cmd_hooks_install()

    assert result == 0

    # Editor hook script copied to .reinicorn/hooks/
    dest_hook = kb_repo / ".reinicorn" / "hooks" / "enforce-doc-templates.sh"
    assert dest_hook.is_file()
    assert "rcorn _check-path" in dest_hook.read_text()

    # Claude Code settings.json updated
    settings_path = kb_repo / ".claude" / "settings.json"
    assert settings_path.is_file()
    settings = json.loads(settings_path.read_text())
    pre_tool = settings["hooks"]["PreToolUse"]
    assert len(pre_tool) == 1
    assert pre_tool[0]["matcher"] == "Write|Edit"

    # Cursor hooks.json updated
    cursor_path = kb_repo / ".cursor" / "hooks.json"
    assert cursor_path.is_file()
    cursor_settings = json.loads(cursor_path.read_text())
    assert cursor_settings["version"] == 1
    assert len(cursor_settings["hooks"]["preToolUse"]) == 1

    # Copilot reinicorn.json updated
    copilot_path = kb_repo / ".github" / "hooks" / "reinicorn.json"
    assert copilot_path.is_file()
    copilot_settings = json.loads(copilot_path.read_text())
    assert copilot_settings["version"] == 1
    assert len(copilot_settings["hooks"]["preToolUse"]) == 1


# --- _merge_cursor_settings tests ---


def test_merge_cursor_settings_creates_new_file(tmp_path: Path):
    settings_path = tmp_path / ".cursor" / "hooks.json"
    entries = [{"command": ".reinicorn/hooks/enforce-doc-templates.sh", "matcher": "Write|Edit"}]
    _merge_cursor_settings(settings_path, entries)
    assert settings_path.is_file()
    settings = json.loads(settings_path.read_text())
    assert settings["version"] == 1
    assert settings["hooks"]["preToolUse"] == entries


def test_merge_cursor_settings_preserves_existing(tmp_path: Path):
    settings_path = tmp_path / "hooks.json"
    settings_path.write_text(json.dumps({
        "version": 1,
        "hooks": {"postToolUse": [{"command": "echo done"}]},
    }))
    entries = [{"command": ".reinicorn/hooks/enforce-doc-templates.sh", "matcher": "Write|Edit"}]
    _merge_cursor_settings(settings_path, entries)
    settings = json.loads(settings_path.read_text())
    assert settings["hooks"]["postToolUse"] == [{"command": "echo done"}]
    assert settings["hooks"]["preToolUse"] == entries


def test_merge_cursor_settings_idempotent(tmp_path: Path):
    settings_path = tmp_path / "hooks.json"
    entries = [{"command": ".reinicorn/hooks/enforce-doc-templates.sh", "matcher": "Write|Edit"}]
    _merge_cursor_settings(settings_path, entries)
    _merge_cursor_settings(settings_path, entries)
    settings = json.loads(settings_path.read_text())
    assert len(settings["hooks"]["preToolUse"]) == 1


# --- _merge_copilot_settings tests ---


def test_merge_copilot_settings_creates_new_file(tmp_path: Path):
    settings_path = tmp_path / ".github" / "hooks" / "reinicorn.json"
    entries = [{"type": "command", "bash": ".reinicorn/hooks/enforce-doc-templates.sh"}]
    _merge_copilot_settings(settings_path, entries)
    assert settings_path.is_file()
    settings = json.loads(settings_path.read_text())
    assert settings["version"] == 1
    assert settings["hooks"]["preToolUse"] == entries


def test_merge_copilot_settings_idempotent(tmp_path: Path):
    settings_path = tmp_path / "reinicorn.json"
    entries = [{"type": "command", "bash": ".reinicorn/hooks/enforce-doc-templates.sh"}]
    _merge_copilot_settings(settings_path, entries)
    _merge_copilot_settings(settings_path, entries)
    settings = json.loads(settings_path.read_text())
    assert len(settings["hooks"]["preToolUse"]) == 1
