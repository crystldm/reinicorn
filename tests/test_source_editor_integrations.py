"""Structural tests for the source repository's tracked editor integrations."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK_NAMES = ("block-raw-kb-git.sh", "enforce-doc-templates.sh")


def test_source_editor_settings_use_reinicorn_hook_directory() -> None:
    claude = json.loads((ROOT / ".claude/settings.json").read_text())
    claude_commands = [
        hook["command"]
        for entry in claude["hooks"]["PreToolUse"]
        for hook in entry["hooks"]
    ]
    cursor = json.loads((ROOT / ".cursor/hooks.json").read_text())
    cursor_commands = [
        entry["command"] for entry in cursor["hooks"]["preToolUse"]
    ]

    relative_expected = {f".reinicorn/hooks/{name}" for name in HOOK_NAMES}
    claude_expected = {
        f"$CLAUDE_PROJECT_DIR/.reinicorn/hooks/{name}" for name in HOOK_NAMES
    }
    assert set(claude_commands) == claude_expected
    assert set(cursor_commands) == relative_expected
    assert not (ROOT / ".reins").exists()


def test_source_hooks_match_package_owned_editor_hooks() -> None:
    for name in HOOK_NAMES:
        source_hook = ROOT / ".reinicorn/hooks" / name
        package_hook = ROOT / "editor-hooks" / name
        assert source_hook.is_file()
        assert source_hook.read_bytes() == package_hook.read_bytes()


def test_source_integrations_enter_cli_through_uv() -> None:
    session_start = (ROOT / ".claude/hooks/session-start.sh").read_text()
    assert "uv run rcorn kb status --compact" in session_start
    assert "uv run rcorn hooks install" in session_start
    assert "uv tool install" not in session_start

    enforce_hook = (ROOT / "editor-hooks/enforce-doc-templates.sh").read_text()
    assert 'uv run rcorn _check-path "$FILE"' in enforce_hook
