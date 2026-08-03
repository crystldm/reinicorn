"""Test that rcorn init installs the SessionStart hook."""

from __future__ import annotations

import json
import stat
from pathlib import Path

from reinicorn.commands.init import cmd_init
from reinicorn.git import run_git


def _git(*args: str, cwd: Path | None = None) -> None:
    run_git(*args, cwd=cwd)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=path)
    _git("config", "user.email", "test@test", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    _git("commit", "--allow-empty", "-m", "init", cwd=path)


def test_init_installs_session_hook(tmp_path: Path):
    """cmd_init creates .claude/settings.json with SessionStart hook."""
    from unittest.mock import patch

    repo = tmp_path / "my-repo"
    _init_repo(repo)

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="my-repo"), \
         patch("reinicorn.commands.init.prompt_platforms", return_value=["claude"]):
        rc = cmd_init(kb_url="unused", local=True, cwd=repo)

    assert rc == 0

    settings = repo / ".claude" / "settings.json"
    assert settings.is_file(), ".claude/settings.json should exist"
    data = json.loads(settings.read_text())
    assert "hooks" in data
    assert "SessionStart" in data["hooks"]

    hook_script = repo / ".claude" / "hooks" / "check-agents-md.sh"
    assert hook_script.is_file(), "hook script should be copied"
    assert hook_script.stat().st_mode & stat.S_IXUSR, "hook script should be executable"


def test_init_preserves_existing_settings(tmp_path: Path):
    """cmd_init merges hook into existing .claude/settings.json."""
    from unittest.mock import patch

    repo = tmp_path / "my-repo"
    _init_repo(repo)

    # Pre-existing settings
    claude_dir = repo / ".claude"
    claude_dir.mkdir()
    existing = {"permissions": {"allow": ["Read"]}}
    (claude_dir / "settings.json").write_text(json.dumps(existing))

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="my-repo"), \
         patch("reinicorn.commands.init.prompt_platforms", return_value=["claude"]):
        rc = cmd_init(kb_url="unused", local=True, cwd=repo)

    assert rc == 0
    data = json.loads((claude_dir / "settings.json").read_text())
    assert data["permissions"]["allow"] == ["Read"]
    assert "SessionStart" in data["hooks"]


def test_init_idempotent_hook(tmp_path: Path):
    """Running init twice does not duplicate the hook entry."""
    from unittest.mock import patch

    repo = tmp_path / "my-repo"
    _init_repo(repo)

    for _ in range(2):
        with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
             patch("reinicorn.commands.init.repo_slug", return_value="my-repo"), \
             patch("reinicorn.commands.init.prompt_platforms", return_value=["claude"]):
            cmd_init(kb_url="unused", local=True, cwd=repo)

    data = json.loads((repo / ".claude" / "settings.json").read_text())
    session_hooks = data["hooks"]["SessionStart"]
    assert len(session_hooks) == 1, "should not duplicate hook entry"


def test_hooks_install_wires_both_editor_hooks(tmp_path: Path, monkeypatch):
    """hooks install copies both editor hook scripts and registers both matchers."""
    from reinicorn.commands.hooks_install import cmd_hooks_install

    run_git("init", "-q", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert cmd_hooks_install() == 0

    assert (tmp_path / ".reinicorn/hooks/enforce-doc-templates.sh").is_file()
    assert (tmp_path / ".reinicorn/hooks/block-raw-kb-git.sh").is_file()

    settings = json.loads((tmp_path / ".claude/settings.json").read_text())
    matchers = {e["matcher"] for e in settings["hooks"]["PreToolUse"]}
    assert matchers == {"Write|Edit", "Bash"}

    cursor = json.loads((tmp_path / ".cursor/hooks.json").read_text())
    commands = {e["command"] for e in cursor["hooks"]["preToolUse"]}
    assert commands == {
        ".reinicorn/hooks/enforce-doc-templates.sh",
        ".reinicorn/hooks/block-raw-kb-git.sh",
    }

    copilot = json.loads((tmp_path / ".github/hooks/reinicorn.json").read_text())
    bashes = {e["bash"] for e in copilot["hooks"]["preToolUse"]}
    assert bashes == {
        ".reinicorn/hooks/enforce-doc-templates.sh",
        ".reinicorn/hooks/block-raw-kb-git.sh",
    }

    # Idempotency: a second run must not duplicate entries
    assert cmd_hooks_install() == 0
    settings = json.loads((tmp_path / ".claude/settings.json").read_text())
    assert len(settings["hooks"]["PreToolUse"]) == 2
    cursor = json.loads((tmp_path / ".cursor/hooks.json").read_text())
    assert len(cursor["hooks"]["preToolUse"]) == 2
    copilot = json.loads((tmp_path / ".github/hooks/reinicorn.json").read_text())
    assert len(copilot["hooks"]["preToolUse"]) == 2
