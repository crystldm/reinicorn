"""Test that --slug overrides the auto-derived repo slug during init."""

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


def _configure_existing_kb(repo: Path) -> None:
    """Mark a repository as a genuine teammate clone: a populated kb submodule
    plus the committed manifest that init writes when it lays down assets."""
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


def test_init_slug_override(tmp_path: Path):
    """cmd_init with slug= uses the override instead of repo_slug()."""
    repo = tmp_path / "my-repo"
    _init_repo(repo)

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="auto-derived"), \
         patch("reinicorn.commands.init.prompt_platforms", return_value=["claude"]):
        rc = cmd_init(kb_url="unused", local=True, cwd=repo, slug="custom-name")

    assert rc == 0
    kb_dir = repo / "kb"
    assert (kb_dir / "custom-name").is_dir(), "should use override slug"
    assert (kb_dir / "custom-name" / "golden-principles.md").is_file()
    assert (kb_dir / "custom-name" / "README.md").read_text().startswith(
        "# custom-name knowledge base\n"
    )
    assert (repo / ".reinicorn-config").read_text() == (
        "REINICORN_KB_SCOPE=custom-name\n"
    )


def _assert_invalid_scope_has_no_side_effects(
    repo: Path,
    *,
    slug: str | None,
    resolved_slug: str,
    local: bool = False,
    create_remote: bool = False,
    kb_name: str | None = None,
) -> None:
    with (
        patch("reinicorn.commands.init.repo_slug", return_value=resolved_slug),
        patch("reinicorn.commands.init._prompt_kb_source") as prompt_source,
        patch("reinicorn.commands.init._create_local_bare") as create_local,
        patch("reinicorn.commands.init._create_github_remote") as create_github,
        patch("reinicorn.commands.init.setup_submodule") as setup,
        patch("reinicorn.commands.init.config_set") as write_config,
        patch("reinicorn.commands.init.cmd_hooks_install") as install_hooks,
    ):
        rc = cmd_init(
            cwd=repo,
            slug=slug,
            local=local,
            create_remote=create_remote,
            kb_name=kb_name,
        )

    assert rc == 1
    prompt_source.assert_not_called()
    create_local.assert_not_called()
    create_github.assert_not_called()
    setup.assert_not_called()
    write_config.assert_not_called()
    install_hooks.assert_not_called()


def test_init_rejects_invalid_explicit_scope_before_local_creation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "my-repo"
    _init_repo(repo)

    _assert_invalid_scope_has_no_side_effects(
        repo,
        slug="../escape",
        resolved_slug="fallback",
        local=True,
    )


def test_init_rejects_invalid_explicit_scope_before_github_creation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "my-repo"
    _init_repo(repo)

    _assert_invalid_scope_has_no_side_effects(
        repo,
        slug="../escape",
        resolved_slug="fallback",
        create_remote=True,
        kb_name="valid-kb",
    )


def test_init_rejects_invalid_resolved_scope_before_prompting(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "my-repo"
    _init_repo(repo)

    _assert_invalid_scope_has_no_side_effects(
        repo,
        slug=None,
        resolved_slug="../escape",
    )


def test_existing_kb_init_persists_explicit_slug(tmp_path: Path) -> None:
    """An explicit scope is persisted in the teammate setup flow."""
    repo = tmp_path / "my-repo"
    _init_repo(repo)
    _configure_existing_kb(repo)

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0):
        rc = cmd_init(cwd=repo, slug="custom-name")

    assert rc == 0
    assert (repo / ".reinicorn-config").read_text() == (
        "REINICORN_KB_SCOPE=custom-name\n"
    )


def test_existing_kb_init_repairs_missing_agents_with_configured_scope(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "my-repo"
    _init_repo(repo)
    _configure_existing_kb(repo)
    (repo / ".reinicorn-config").write_text("REINICORN_KB_SCOPE=configured\n")
    template = tmp_path / "AGENTS.md"
    template.write_text("Read `kb/{repo}/README.md`.\n")

    with patch("reinicorn.commands.init.get_asset_path", return_value=template), \
         patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch(
             "reinicorn.git.repo_slug",
             side_effect=AssertionError("configured scope must be preferred"),
         ):
        assert cmd_init(cwd=repo) == 0

    assert (repo / "AGENTS.md").read_text() == (
        "Read `kb/configured/README.md`.\n"
    )


def test_existing_kb_init_repairs_missing_agents_with_origin_scope(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "my-repo"
    _init_repo(repo)
    _configure_existing_kb(repo)
    template = tmp_path / "AGENTS.md"
    template.write_text("Read `kb/{repo}/README.md`.\n")

    with patch("reinicorn.commands.init.get_asset_path", return_value=template), \
         patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.git.repo_slug", return_value="origin-derived"):
        assert cmd_init(cwd=repo) == 0

    assert (repo / "AGENTS.md").read_text() == (
        "Read `kb/origin-derived/README.md`.\n"
    )


def test_existing_kb_init_rejects_invalid_explicit_slug(tmp_path: Path) -> None:
    """Invalid teammate-flow scopes fail before config or hook setup."""
    repo = tmp_path / "my-repo"
    _init_repo(repo)
    _configure_existing_kb(repo)

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0) as hooks:
        rc = cmd_init(cwd=repo, slug="../escape")

    assert rc == 1
    assert not (repo / ".reinicorn-config").exists()
    hooks.assert_not_called()


def test_init_without_slug_uses_repo_slug(tmp_path: Path):
    """cmd_init without slug= falls back to repo_slug()."""
    repo = tmp_path / "my-repo"
    _init_repo(repo)

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="auto-derived"), \
         patch("reinicorn.commands.init.prompt_platforms", return_value=["claude"]):
        rc = cmd_init(kb_url="unused", local=True, cwd=repo)

    assert rc == 0
    kb_dir = repo / "kb"
    assert (kb_dir / "auto-derived").is_dir(), "should use auto-derived slug"


def test_init_substitutes_repo_in_agents_md(tmp_path: Path):
    """cmd_init substitutes {repo} with the slug in AGENTS.md."""
    repo = tmp_path / "my-repo"
    _init_repo(repo)

    template = tmp_path / "template" / "AGENTS.md"
    template.parent.mkdir()
    template.write_text("Read `kb/{repo}/README.md`.\n")

    with patch("reinicorn.commands.init.get_asset_path") as asset_path, \
         patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="my-repo"), \
         patch("reinicorn.commands.init.prompt_platforms", return_value=["claude"]):
        asset_path.side_effect = (
            lambda name: template if name == "templates/AGENTS.md" else None
        )
        rc = cmd_init(kb_url="unused", local=True, cwd=repo)

    assert rc == 0
    agents_md = (repo / "AGENTS.md").read_text()
    assert "kb/my-repo/README.md" in agents_md
    assert "{repo}" not in agents_md
