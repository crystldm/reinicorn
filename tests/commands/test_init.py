"""Tests for reins init — unified init command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from reinicorn.commands.init import cmd_init
from reinicorn.config import config_get
from reinicorn.git import run_git


def _git(args: list[str], cwd: Path) -> None:
    run_git(*args, cwd=cwd)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q", "-b", "main"], path)
    _git(["config", "user.email", "test@test.com"], path)
    _git(["config", "user.name", "Test User"], path)
    (path / "README.md").write_text("# Test\n")
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", "init"], path)


@pytest.fixture
def existing_repo(tmp_path: Path) -> Path:
    """An existing git repo with no kb."""
    repo = tmp_path / "existing"
    _init_repo(repo)
    return repo


@pytest.fixture
def seeded_bare(tmp_path: Path) -> Path:
    """A bare repo with a commit (ready to clone as kb)."""
    bare = tmp_path / "kb.git"
    bare.mkdir()
    _git(["init", "--bare", "-q", "-b", "main"], bare)
    staging = tmp_path / "staging"
    _init_repo(staging)
    _git(["-c", "protocol.file.allow=always", "remote", "add", "origin", str(bare)], staging)
    _git(["-c", "protocol.file.allow=always", "push", "-q", "origin", "main"], staging)
    return bare


def test_init_rejects_non_git_dir(tmp_path: Path):
    """init should fail with helpful message if not in a git repo."""
    result = cmd_init(cwd=tmp_path)
    assert result == 1


def test_init_with_kb_url_flag(existing_repo: Path, seeded_bare: Path, tmp_path: Path):
    """--kb-url flag skips interactive prompt."""
    # Create a fake reins root with assets
    r_root = tmp_path / "r_root"
    r_root.mkdir()
    agents = r_root / "templates" / "AGENTS.md"
    agents.parent.mkdir()
    agents.write_text("# AGENTS\n")
    skills = r_root / ".agents" / "skills"
    skills.mkdir(parents=True)
    (skills / "test-skill.md").write_text("# Test Skill\n")

    with patch("reinicorn.commands.init.reinicorn_root", return_value=r_root), \
         patch("reinicorn.commands.init.get_asset_path") as mock_asset, \
         patch("reinicorn.commands.init.prompt_platforms", return_value=["claude"]):
        def _resolve(name: str) -> Path | None:
            p = r_root / name
            return p if p.exists() else None
        mock_asset.side_effect = _resolve

        result = cmd_init(kb_url=str(seeded_bare), cwd=existing_repo)

    assert result == 0
    assert (existing_repo / "kb").is_dir()
    assert (existing_repo / "kb" / ".git").is_dir()
    assert "kb/" in (existing_repo / ".gitignore").read_text()
    assert (existing_repo / "AGENTS.md").is_file()


def test_init_renders_generic_agents_once_and_preserves_it(
    existing_repo: Path, seeded_bare: Path, tmp_path: Path
) -> None:
    template = tmp_path / "templates" / "AGENTS.md"
    template.parent.mkdir()
    template.write_text(
        "# {repo}\n\nRead `kb/{repo}/README.md`.\n<!-- UNPOPULATED -->\n"
    )

    def _resolve(name: str) -> Path | None:
        return template if name == "templates/AGENTS.md" else None

    with patch("reinicorn.commands.init.get_asset_path", side_effect=_resolve), \
         patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.prompt_platforms", return_value=[]):
        assert cmd_init(
            kb_url=str(seeded_bare), cwd=existing_repo, slug="sample"
        ) == 0

    agents = existing_repo / "AGENTS.md"
    assert "kb/sample/README.md" in agents.read_text()
    assert "<!-- UNPOPULATED" in agents.read_text()

    agents.write_bytes(b"# User owned\n")
    before = agents.read_bytes()
    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0):
        assert cmd_init(cwd=existing_repo) == 0
    assert agents.read_bytes() == before


def test_init_reports_missing_packaged_agents_template(
    existing_repo: Path,
    seeded_bare: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    template = tmp_path / "templates" / "AGENTS.md"

    def _resolve(name: str) -> Path | None:
        if name == "templates/AGENTS.md" and template.is_file():
            return template
        return None

    with patch("reinicorn.commands.init.get_asset_path", side_effect=_resolve), \
         patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.prompt_platforms", return_value=[]):
        assert cmd_init(
            kb_url=str(seeded_bare), cwd=existing_repo, slug="sample"
        ) == 1

    output = capsys.readouterr().out
    assert (
        "Missing packaged template 'templates/AGENTS.md'. Reinstall Reinicorn, "
        "then rerun 'rcorn init'."
    ) in output
    assert not (existing_repo / "kb").exists()
    assert not (existing_repo / ".reinicorn" / "manifest.json").exists()
    assert "Reins initialized!" not in output

    template.parent.mkdir()
    template.write_text("# {repo}\n\nRead `kb/{repo}/README.md`.\n")
    with patch("reinicorn.commands.init.get_asset_path", side_effect=_resolve), \
         patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.prompt_platforms", return_value=[]):
        assert cmd_init(
            kb_url=str(seeded_bare), cwd=existing_repo, slug="sample"
        ) == 0

    assert "kb/sample/README.md" in (existing_repo / "AGENTS.md").read_text()
    assert config_get("REINICORN_KB_SCOPE", root=existing_repo) == "sample"
    assert config_get("REINICORN_KB_REMOTE", root=existing_repo) == str(seeded_bare)
    assert (existing_repo / ".reinicorn/manifest.json").is_file()


def test_copy_agent_instructions_preserves_existing_directory(
    tmp_path: Path,
) -> None:
    from reinicorn.commands.init import _copy_agent_instructions

    destination = tmp_path / "AGENTS.md"
    destination.mkdir()

    with patch("reinicorn.commands.init.get_asset_path") as get_asset:
        assert _copy_agent_instructions(tmp_path, tmp_path, "sample") is True

    get_asset.assert_not_called()
    assert destination.is_dir()


def test_copy_agent_instructions_preserves_dangling_symlink(
    tmp_path: Path,
) -> None:
    from reinicorn.commands.init import _copy_agent_instructions

    target = tmp_path / "outside" / "AGENTS.md"
    destination = tmp_path / "AGENTS.md"
    destination.symlink_to(target)

    with patch("reinicorn.commands.init.get_asset_path") as get_asset:
        assert _copy_agent_instructions(tmp_path, tmp_path, "sample") is True

    get_asset.assert_not_called()
    assert destination.is_symlink()
    assert not target.exists()


def test_init_detects_existing_kb(kb_repo: Path):
    """init on a genuine teammate clone (kb + committed manifest) installs
    hooks only — no asset re-copy."""
    manifest = kb_repo / ".reinicorn" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"reinicorn_version": "0.0.0", "files": {}}')

    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init._setup_assets") as mock_setup:
        result = cmd_init(cwd=kb_repo)

    # Should succeed — just installs hooks, never lays down assets
    assert result == 0
    mock_setup.assert_not_called()


def test_init_existing_kb_without_manifest_sets_up_assets(
    kb_repo: Path, tmp_path: Path
):
    """init on a repo whose kb clone exists but was never fully set up
    (no manifest) should lay down assets and write a manifest, without
    re-cloning kb."""
    r_root = tmp_path / "r_root"
    r_root.mkdir()
    (r_root / "templates").mkdir()
    (r_root / "templates" / "AGENTS.md").write_text("# {repo}\n")
    skills = r_root / ".agents" / "skills"
    skills.mkdir(parents=True)
    (skills / "test-skill.md").write_text("# Test Skill\n")

    assert not (kb_repo / ".reinicorn" / "manifest.json").is_file()

    with patch("reinicorn.commands.init.reinicorn_root", return_value=r_root), \
         patch("reinicorn.commands.init.get_asset_path") as mock_asset, \
         patch("reinicorn.commands.init.repo_slug", return_value="testproject"), \
         patch("reinicorn.commands.init.prompt_platforms", return_value=["claude"]), \
         patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.setup_kb_clone") as mock_setup_kb_clone:
        def _resolve(name: str) -> Path | None:
            p = r_root / name
            return p if p.exists() else None
        mock_asset.side_effect = _resolve

        result = cmd_init(cwd=kb_repo)

    assert result == 0
    # Kb clone already present — must NOT be re-cloned
    mock_setup_kb_clone.assert_not_called()
    # Assets laid down + manifest written
    assert (kb_repo / ".reinicorn" / "manifest.json").is_file()
    assert (kb_repo / "AGENTS.md").is_file()
    assert (kb_repo / ".agents" / "skills" / "test-skill.md").is_file()


def test_init_with_local_flag(existing_repo: Path, tmp_path: Path):
    """--local flag creates a local bare repo."""
    r_root = tmp_path / "r_root"
    r_root.mkdir()
    template = r_root / "templates" / "AGENTS.md"
    template.parent.mkdir()
    template.write_text("# AGENTS\n")

    with patch("reinicorn.commands.init.reinicorn_root", return_value=r_root), \
         patch("reinicorn.commands.init.get_asset_path") as mock_asset, \
         patch("reinicorn.commands.init.repo_slug", return_value="existing"), \
         patch("reinicorn.commands.init.prompt_platforms", return_value=["claude"]):
        def _resolve(name: str) -> Path | None:
            p = r_root / name
            return p if p.exists() else None
        mock_asset.side_effect = _resolve

        result = cmd_init(local=True, cwd=existing_repo)

    assert result == 0
    assert (existing_repo / "kb").is_dir()


def test_init_copies_lint_config(existing_repo: Path, seeded_bare: Path, tmp_path: Path):
    """init should copy linters/.lint-config.json to target repo."""
    r_root = tmp_path / "r_root"
    r_root.mkdir()
    template = r_root / "templates" / "AGENTS.md"
    template.parent.mkdir()
    template.write_text("# AGENTS\n")
    lint_dir = r_root / "linters"
    lint_dir.mkdir()
    (lint_dir / ".lint-config.json").write_text('{"rules": []}')

    with patch("reinicorn.commands.init.reinicorn_root", return_value=r_root), \
         patch("reinicorn.commands.init.get_asset_path") as mock_asset, \
         patch("reinicorn.commands.init.prompt_platforms", return_value=["claude"]):
        def _resolve(name: str) -> Path | None:
            p = r_root / name
            return p if p.exists() else None
        mock_asset.side_effect = _resolve
        result = cmd_init(kb_url=str(seeded_bare), cwd=existing_repo)

    assert result == 0
    assert (existing_repo / "linters" / ".lint-config.json").is_file()


def test_copy_skills_honours_configured_skills_dir(tmp_path: Path) -> None:
    """The native-skill copy destination follows REINICORN_SKILLS_DIR — only
    the packaged asset SOURCE path stays fixed at `.agents/skills`."""
    from reinicorn.commands.init import _copy_skills

    r_root = tmp_path / "r_root"
    skills_src = r_root / ".agents" / "skills" / "test-skill"
    skills_src.mkdir(parents=True)
    (skills_src / "SKILL.md").write_text("# Test Skill\n")

    target = tmp_path / "target"
    target.mkdir()
    (target / ".reinicorn-config").write_text("REINICORN_SKILLS_DIR=custom/skills\n")

    def _resolve(name: str) -> Path | None:
        p = r_root / name
        return p if p.exists() else None

    with patch("reinicorn.commands.init.get_asset_path", side_effect=_resolve):
        _copy_skills(r_root, target)

    assert (target / "custom" / "skills" / "test-skill" / "SKILL.md").is_file()
    assert not (target / ".agents" / "skills").exists()


def _wiring_doc_path(repo: Path) -> Path:
    return repo / ".agents/skills/using-reinicorn/references/skillset-wiring.md"


def _setup_init_r_root(tmp_path: Path) -> Path:
    r_root = tmp_path / "r_root"
    r_root.mkdir()
    (r_root / "templates").mkdir()
    (r_root / "templates" / "AGENTS.md").write_text("# {repo}\n")
    skills = r_root / ".agents" / "skills"
    skills.mkdir(parents=True)
    (skills / "test-skill.md").write_text("# Test Skill\n")
    return r_root


def test_init_regenerates_wiring_doc_without_lock(kb_repo: Path, tmp_path: Path) -> None:
    """No skillset lock installed → init still leaves the wiring doc present,
    rendered registry-only (em dash in every skills cell)."""
    r_root = _setup_init_r_root(tmp_path)

    with patch("reinicorn.commands.init.reinicorn_root", return_value=r_root), \
         patch("reinicorn.commands.init.get_asset_path") as mock_asset, \
         patch("reinicorn.commands.init.repo_slug", return_value="testproject"), \
         patch("reinicorn.commands.init.prompt_platforms", return_value=["claude"]), \
         patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.setup_kb_clone"):
        def _resolve(name: str) -> Path | None:
            p = r_root / name
            return p if p.exists() else None
        mock_asset.side_effect = _resolve

        result = cmd_init(cwd=kb_repo)

    assert result == 0
    doc = _wiring_doc_path(kb_repo)
    assert doc.is_file()
    content = doc.read_text()
    rows = [line for line in content.splitlines() if line.startswith("| ")][1:]
    assert rows
    assert all(row.endswith("| — |") for row in rows)


def test_init_regenerates_wiring_doc_with_lock(kb_repo: Path, tmp_path: Path) -> None:
    """A pre-existing skillset lock's wiring populates the doc's skills
    column after init lays down assets."""
    from reinicorn.skillset.adapter import WiringEntry
    from reinicorn.skillset.lockfile import SkillsetLock, write_lock

    r_root = _setup_init_r_root(tmp_path)
    write_lock(
        kb_repo,
        SkillsetLock(
            adapter="superpowers",
            repo="obra/superpowers",
            commit="a" * 40,
            archive_sha256="b" * 64,
            files={},
            wiring={"spec": WiringEntry(skills=("alpha",))},
        ),
    )

    with patch("reinicorn.commands.init.reinicorn_root", return_value=r_root), \
         patch("reinicorn.commands.init.get_asset_path") as mock_asset, \
         patch("reinicorn.commands.init.repo_slug", return_value="testproject"), \
         patch("reinicorn.commands.init.prompt_platforms", return_value=["claude"]), \
         patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.setup_kb_clone"):
        def _resolve(name: str) -> Path | None:
            p = r_root / name
            return p if p.exists() else None
        mock_asset.side_effect = _resolve

        result = cmd_init(cwd=kb_repo)

    assert result == 0
    content = _wiring_doc_path(kb_repo).read_text()
    spec_row = next(
        line for line in content.splitlines() if line.startswith("| spec |")
    )
    assert "alpha" in spec_row


def test_cli_init_dispatches_with_flags():
    """reins init --kb-url should pass the flag through to cmd_init."""
    from reinicorn.cli import main

    with patch("reinicorn.commands.init.cmd_init", return_value=0) as mock:
        result = main(["init", "--kb-url", "git@example.com:test/kb.git"])
    assert result == 0
    mock.assert_called_once_with(
        kb_url="git@example.com:test/kb.git",
        local=False,
        create_remote=False,
        kb_name=None,
        slug=None,
        platforms_raw=None,
    )
