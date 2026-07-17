"""Test that Reinicorn init writes a manifest after asset copy."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from reinicorn.commands.init import cmd_init
from reinicorn.git import run_git


def test_init_writes_manifest(tmp_path: Path):
    """cmd_init creates .reinicorn/manifest.json after setup."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git("init", "-q", "-b", "main", str(repo))
    run_git("-C", str(repo), "config", "user.email", "test@test.com")
    run_git("-C", str(repo), "config", "user.name", "Test")
    run_git("-C", str(repo), "commit", "--allow-empty", "-m", "init")

    with patch("reinicorn.commands.init.setup_submodule"), \
         patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="test-repo"), \
         patch("reinicorn.commands.init._prompt_platforms", return_value=["claude"]):
        rc = cmd_init(kb_url="https://example.com/kb.git", cwd=repo)

    assert rc == 0
    manifest = repo / ".reinicorn" / "manifest.json"
    assert manifest.is_file()
    data = json.loads(manifest.read_text())
    assert "reinicorn_version" in data
    assert "files" in data
