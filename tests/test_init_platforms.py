"""Tests for platform instruction file generation during init."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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


def test_init_generates_claude_md(tmp_path: Path):
    """When claude platform selected, generates CLAUDE.md containing AGENTS.md and the slug."""
    repo = tmp_path / "my-repo"
    _init_repo(repo)

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="my-repo"), \
         patch("reinicorn.commands.init._prompt_platforms", return_value=["claude"]):
        rc = cmd_init(kb_url="unused", local=True, cwd=repo)

    assert rc == 0
    claude_md = repo / "CLAUDE.md"
    assert claude_md.is_file(), "CLAUDE.md should be generated"
    content = claude_md.read_text()
    assert "AGENTS.md" in content
    assert "my-repo" in content or "{repo}" not in content


def test_init_generates_all_platforms(tmp_path: Path):
    """All 4 platforms selected: claude/cursor/copilot files exist; no GEMINI.md or codex file."""
    repo = tmp_path / "my-repo"
    _init_repo(repo)

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="my-repo"), \
         patch("reinicorn.commands.init._prompt_platforms",
               return_value=["claude", "cursor", "copilot", "codex"]):
        rc = cmd_init(kb_url="unused", local=True, cwd=repo)

    assert rc == 0
    assert (repo / "CLAUDE.md").is_file()
    assert (repo / ".cursor" / "rules" / "reinicorn.mdc").is_file()
    assert (repo / ".github" / "copilot-instructions.md").is_file()
    assert not (repo / "GEMINI.md").exists()
    assert not (repo / "CODEX.md").exists()


def test_codex_platform_installs_no_extra_file(tmp_path: Path):
    """Codex reads AGENTS.md natively — selecting it must not write any new file."""
    from reinicorn.commands.init import _install_platform_instructions

    before = set(tmp_path.rglob("*"))
    _install_platform_instructions(tmp_path, "myrepo", ["codex"])
    after = set(tmp_path.rglob("*"))
    assert before == after


def test_init_skips_existing_platform_file(tmp_path: Path):
    """Pre-existing CLAUDE.md is not overwritten."""
    repo = tmp_path / "my-repo"
    _init_repo(repo)

    # Create a pre-existing CLAUDE.md
    existing_content = "# My custom CLAUDE.md\nDo not overwrite me.\n"
    (repo / "CLAUDE.md").write_text(existing_content)

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="my-repo"), \
         patch("reinicorn.commands.init._prompt_platforms", return_value=["claude"]):
        rc = cmd_init(kb_url="unused", local=True, cwd=repo)

    assert rc == 0
    assert (repo / "CLAUDE.md").read_text() == existing_content


def test_init_substitutes_repo_slug(tmp_path: Path):
    """'{repo}' is replaced with actual slug, no literal '{repo}' remains."""
    repo = tmp_path / "my-repo"
    _init_repo(repo)

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="my-repo"), \
         patch("reinicorn.commands.init._prompt_platforms", return_value=["claude"]):
        rc = cmd_init(kb_url="unused", local=True, cwd=repo)

    assert rc == 0
    content = (repo / "CLAUDE.md").read_text()
    assert "{repo}" not in content, "template variable should be substituted"
    assert "my-repo" in content
