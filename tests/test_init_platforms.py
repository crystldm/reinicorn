"""Tests for platform instruction file generation during init."""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from reinicorn.commands.init import _init_path, cmd_init
from reinicorn.git import run_git


def _git(*args: str, cwd: Path | None = None) -> None:
    run_git(*args, cwd=cwd)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=path)
    _git("config", "user.email", "test@test", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    _git("commit", "--allow-empty", "-m", "init", cwd=path)


def test_init_path_classifies_platform_handling_paths(tmp_path: Path):
    assert _init_path(tmp_path) == "full"

    (tmp_path / ".gitmodules").write_text(
        '[submodule "kb"]\n'
        "\tpath = kb\n"
        "\turl = https://example.com/kb.git\n"
    )
    assert _init_path(tmp_path) == "assets_only"

    manifest = tmp_path / ".reinicorn" / "manifest.json"
    manifest.parent.mkdir()
    manifest.write_text("{}")
    assert _init_path(tmp_path) == "hooks_only"


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


def test_platform_specs_describe_installable_and_agents_only_platforms():
    """Each platform either has both install paths or relies on AGENTS.md."""
    from reinicorn.commands.init_platforms import PLATFORM_SPECS

    codex = next(spec for spec in PLATFORM_SPECS if spec.key == "codex")
    assert codex.template_path is None
    assert codex.destination_path is None
    assert all(
        (spec.template_path is None) == (spec.destination_path is None)
        for spec in PLATFORM_SPECS
    )


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


def test_init_platforms_raw_empty_skips_prompt_and_installs_no_platform_files(
    tmp_path: Path,
):
    repo = tmp_path / "my-repo"
    _init_repo(repo)

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="my-repo"), \
         patch("reinicorn.commands.init._prompt_platforms") as prompt:
        rc = cmd_init(kb_url="unused", local=True, cwd=repo, platforms_raw="")

    assert rc == 0
    prompt.assert_not_called()
    assert not (repo / "CLAUDE.md").exists()
    assert not (repo / ".cursor" / "rules" / "reinicorn.mdc").exists()
    assert not (repo / ".github" / "copilot-instructions.md").exists()


def test_init_platforms_raw_skips_prompt_and_installs_cursor(tmp_path: Path):
    repo = tmp_path / "my-repo"
    _init_repo(repo)

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="my-repo"), \
         patch("reinicorn.commands.init._prompt_platforms") as prompt:
        rc = cmd_init(
            kb_url="unused", local=True, cwd=repo, platforms_raw="cursor"
        )

    assert rc == 0
    prompt.assert_not_called()
    assert (repo / ".cursor" / "rules" / "reinicorn.mdc").is_file()
    assert not (repo / "CLAUDE.md").exists()


def test_init_platforms_raw_unknown_key_errors(tmp_path: Path, capsys):
    repo = tmp_path / "my-repo"
    _init_repo(repo)

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="my-repo"), \
         patch("reinicorn.commands.init._prompt_platforms") as prompt:
        rc = cmd_init(
            kb_url="unused", local=True, cwd=repo, platforms_raw="nope"
        )

    assert rc == 1
    prompt.assert_not_called()
    err = capsys.readouterr().out
    assert "nope" in err
    assert "claude" in err


def test_existing_kb_without_manifest_validates_platforms_before_side_effects(
    tmp_path: Path,
):
    """Invalid --platforms must not update submodules or write the scope config."""
    repo = tmp_path / "existing-kb"
    _init_repo(repo)
    (repo / ".gitmodules").write_text(
        '[submodule "kb"]\n'
        "\tpath = kb\n"
        "\turl = https://example.com/kb.git\n"
    )

    with patch(
        "reinicorn.commands.init.run_git",
        return_value=CompletedProcess([], 0),
    ) as mock_run_git, patch(
        "reinicorn.commands.init.config_set"
    ) as mock_config_set, patch(
        "reinicorn.commands.init._preflight_agent_instructions",
        return_value=(True, None),
    ):
        rc = cmd_init(cwd=repo, slug="existing-kb", platforms_raw="nope")

    assert rc == 1
    mock_config_set.assert_not_called()
    mock_run_git.assert_called_once_with(
        "rev-parse", "--git-dir", check=False, cwd=repo
    )


def test_init_platforms_raw_ignored_on_hooks_only_teammate_clone(
    tmp_path: Path, capsys
):
    """Hooks-only path must not hard-fail on --platforms (even unknown keys)."""
    repo = tmp_path / "teammate-repo"
    _init_repo(repo)
    (repo / ".gitmodules").write_text(
        '[submodule "kb"]\n'
        "\tpath = kb\n"
        "\turl = https://example.com/kb.git\n"
    )
    kb_dir = repo / "kb"
    kb_dir.mkdir()
    (kb_dir / "README.md").write_text("# Existing kb\n")
    manifest = repo / ".reinicorn" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"reinicorn_version": "0.0.0", "files": {}}')

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init._setup_assets") as mock_setup, \
         patch("reinicorn.commands.init._prompt_platforms") as prompt:
        rc = cmd_init(cwd=repo, platforms_raw="nope")

    assert rc == 0
    mock_setup.assert_not_called()
    prompt.assert_not_called()
    out = capsys.readouterr().out
    assert "--platforms" in out
    assert "ignoring" in out.lower()


def test_parse_platforms_flag_dedup_and_order():
    from reinicorn.commands.init import _parse_platforms_flag

    assert _parse_platforms_flag("codex, claude,claude") == ["claude", "codex"]


def test_parse_platforms_flag_case_insensitive():
    from reinicorn.commands.init import _parse_platforms_flag

    assert _parse_platforms_flag("Claude") == ["claude"]
    assert _parse_platforms_flag("CURSOR,Codex") == ["cursor", "codex"]


def test_parse_platforms_flag_empty_string():
    from reinicorn.commands.init import _parse_platforms_flag

    assert _parse_platforms_flag("") == []


def test_cli_accepts_platforms_flag():
    import argparse

    from reinicorn.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(
        ["init", "--local", "--platforms", "cursor,claude"]
    )
    assert args.platforms == "cursor,claude"
    init_parser = next(
        action.choices["init"]
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    help_text = init_parser.format_help()
    assert "case-insensitive" in help_text
    assert "skip interactive prompt" in help_text
    assert "claude,cursor,copilot,codex" not in help_text
