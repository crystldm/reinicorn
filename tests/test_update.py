"""Tests for reins update command."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from reinicorn.manifest import write_manifest


def _setup_repo_with_manifest(tmp_path: Path, *, version: str = "0.1.0") -> Path:
    """Create a repo dir with some assets and a manifest."""
    repo = tmp_path / "repo"
    repo.mkdir()
    skills = repo / ".agents" / "skills" / "brainstorming"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# Brainstorming v1\n")
    (repo / "AGENTS.md").write_text("# Agents v1\n")
    write_manifest(repo, version=version)
    return repo


def _setup_package_assets(tmp_path: Path) -> Path:
    """Create fake package assets directory."""
    assets = tmp_path / "assets"
    skills = assets / "skills" / "brainstorming"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# Brainstorming v2\n")
    (assets / "AGENTS.md").write_text("# Agents v2\n")
    return assets


def test_update_overwrites_unchanged_files(tmp_path: Path):
    """Files matching manifest checksum are overwritten with new version."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path)
    assets = _setup_package_assets(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update()

    assert rc == 0
    assert (repo / "AGENTS.md").read_bytes() == b"# Agents v1\n"
    assert (repo / ".agents/skills/brainstorming/SKILL.md").read_text() == "# Brainstorming v2\n"


def test_update_skips_locally_modified_files(tmp_path: Path):
    """Files modified by user are skipped."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path)
    agents = repo / "AGENTS.md"
    agents.write_bytes(b"# My Custom Agents\r\n")
    before = agents.read_bytes()
    assets = _setup_package_assets(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update()

    assert rc == 0
    assert agents.read_bytes() == before


def test_collect_package_files_excludes_agents_template(tmp_path: Path) -> None:
    from reinicorn.commands.update import _collect_package_files

    assets = _setup_package_assets(tmp_path)
    templates = assets / "templates"
    templates.mkdir()
    (templates / "AGENTS.md").write_text("# Package template\n")

    package_files = _collect_package_files(assets)
    assert all("AGENTS.md" not in path for path in package_files)


def test_update_asset_discovery_does_not_probe_agents() -> None:
    from reinicorn.commands.update import _get_asset_sources

    with patch("reinicorn.commands.update.get_asset_path", return_value=None) as asset_path:
        assert _get_asset_sources() is None

    assert all("AGENTS" not in call.args[0] for call in asset_path.call_args_list)


def test_update_missing_asset_error_does_not_claim_agents_is_managed(
    tmp_path: Path, capsys
) -> None:
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path)
    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=None):
        assert cmd_update() == 1

    assert "AGENTS" not in capsys.readouterr().out


def test_update_adds_new_files(tmp_path: Path):
    """Files in package but not in manifest are added."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path)
    assets = _setup_package_assets(tmp_path)
    new_skill = assets / "skills" / "debugging"
    new_skill.mkdir(parents=True)
    (new_skill / "SKILL.md").write_text("# Debugging\n")

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update()

    assert rc == 0
    assert (repo / ".agents/skills/debugging/SKILL.md").read_text() == "# Debugging\n"


def test_update_already_up_to_date(tmp_path: Path):
    """Same version as manifest → early exit."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")

    with patch("reinicorn.commands.update._get_package_version", return_value="0.1.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo):
        rc = cmd_update()

    assert rc == 0


def test_update_sanitizes_legacy_agents_ownership_when_already_current(
    tmp_path: Path, capsys
) -> None:
    """Legacy AGENTS ownership is removed without considering the user file."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    agents = repo / "AGENTS.md"
    agents.write_bytes(b"# User owned\r\n")
    before = agents.read_bytes()
    manifest_path = repo / ".reinicorn" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    managed_skill = repo / ".agents/skills/brainstorming/SKILL.md"
    managed_skill.write_text("# Locally modified\n")
    manifest["migration_metadata"] = {"source": "legacy", "attempt": 7}
    manifest["files"]["AGENTS.md"] = {"sha256": "legacy-package-checksum"}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    expected = deepcopy(manifest)
    del expected["files"]["AGENTS.md"]

    with patch("reinicorn.commands.update._get_package_version", return_value="0.1.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("builtins.input", side_effect=AssertionError("AGENTS must not prompt")):
        assert cmd_update() == 0

    assert agents.read_bytes() == before
    assert "AGENTS" not in capsys.readouterr().out
    rewritten = json.loads(manifest_path.read_text())
    assert rewritten == expected


def test_update_warns_about_removed_upstream(tmp_path: Path, capsys):
    """Files in manifest but not in package trigger a warning."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path)
    removed = repo / ".agents" / "skills" / "removed" / "SKILL.md"
    removed.parent.mkdir()
    removed.write_text("# Removed\n")
    write_manifest(repo, version="0.1.0")
    # Package assets that do not include the removed managed skill.
    assets = tmp_path / "assets"
    skills = assets / "skills" / "brainstorming"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# Brainstorming v2\n")

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update()

    assert rc == 0
    captured = capsys.readouterr()
    assert "Removed upstream" in captured.out
    assert ".agents/skills/removed/SKILL.md" in captured.out


def test_update_cli_dispatch(tmp_path: Path):
    """reins update dispatches to cmd_update."""
    from reinicorn.cli import main

    repo = _setup_repo_with_manifest(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.1.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo):
        rc = main(["update"])

    assert rc == 0


def test_update_shows_upgrade_notes(tmp_path: Path, capsys):
    """Upgrade notes between versions are displayed."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    assets = _setup_package_assets(tmp_path)

    # Create upgrade notes in the asset root
    upgrades = assets / "upgrades"
    upgrades.mkdir()
    (upgrades / "v0.2.0.md").write_text("# v0.2.0\n\n- New brainstorming template\n")

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update()

    assert rc == 0
    captured = capsys.readouterr()
    assert "v0.2.0" in captured.out
    assert "brainstorming template" in captured.out


def test_update_version_comparison_handles_minor_gt_9(tmp_path: Path, capsys):
    """Version 0.10.0 is correctly treated as greater than 0.9.0."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path, version="0.9.0")
    assets = _setup_package_assets(tmp_path)

    upgrades = assets / "upgrades"
    upgrades.mkdir()
    (upgrades / "v0.10.0.md").write_text("# v0.10.0\n\n- Big update\n")
    # v0.2.0 should NOT show (it's before 0.9.0)
    (upgrades / "v0.2.0.md").write_text("# v0.2.0\n\n- Old update\n")

    with patch("reinicorn.commands.update._get_package_version", return_value="0.10.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update()

    assert rc == 0
    captured = capsys.readouterr()
    assert "Big update" in captured.out
    assert "Old update" not in captured.out


def test_update_does_not_readd_deleted_agents_file(tmp_path: Path):
    """A deleted user-owned AGENTS.md remains deleted."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path)
    (repo / "AGENTS.md").unlink()
    assets = _setup_package_assets(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets), \
         patch("builtins.input", return_value="y"):
        rc = cmd_update()

    assert rc == 0
    assert not (repo / "AGENTS.md").is_file()


def test_update_diff_shows_changes(tmp_path: Path, capsys):
    """--diff flag shows diff between repo and upstream."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path)
    skill = repo / ".agents" / "skills" / "brainstorming" / "SKILL.md"
    skill.write_text("# My Custom Skill\n")
    assets = _setup_package_assets(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update(diff_target="brainstorming/SKILL.md")

    assert rc == 0
    captured = capsys.readouterr()
    assert "---" in captured.out
    assert "My Custom Skill" in captured.out


def test_update_never_reclaims_user_owned_maps(tmp_path: Path) -> None:
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path)
    agents = repo / "AGENTS.md"
    readme = repo / "kb" / "sample" / "README.md"
    readme.parent.mkdir(parents=True)
    agents.write_text("# User instructions\n")
    readme.write_text("# Team KB map\n")
    before = (agents.read_bytes(), readme.read_bytes())

    assets = _setup_package_assets(tmp_path)
    with patch("reinicorn.commands.update._get_package_version", return_value="99.0.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        assert cmd_update() == 0

    assert (agents.read_bytes(), readme.read_bytes()) == before
    manifest = json.loads((repo / ".reinicorn/manifest.json").read_text())
    assert "AGENTS.md" not in manifest["files"]
    assert not any(name.startswith("kb/") for name in manifest["files"])


def _fake_get_asset_path(root: Path):
    """Return a get_asset_path stand-in that resolves probes under `root`."""

    def _resolve(name: str) -> Path | None:
        candidate = root / name
        return candidate if candidate.exists() else None

    return _resolve


def test_get_asset_sources_editable_layout_returns_repo_root(tmp_path: Path):
    """Editable installs keep skills under .agents/skills while hooks/ and
    linters/ sit at the repo root. _get_asset_sources must return the repo
    root — not the .agents/ subdir — so the sibling assets stay discoverable.

    Regression (ported from PR #31): it previously returned found.parent
    (=.agents/) for a ".agents/skills" hit, so 'rcorn update' silently synced
    skills only and dropped hooks/linters.
    """
    from reinicorn.commands import update

    root = tmp_path / "repo"
    (root / ".agents" / "skills" / "brainstorming").mkdir(parents=True)
    (root / ".agents/skills/brainstorming/SKILL.md").write_text("x\n")
    (root / "hooks").mkdir()
    (root / "hooks/pre-push").write_text("#!/bin/sh\n")
    (root / "editor-hooks").mkdir()
    (root / "editor-hooks/block-raw-kb-git.sh").write_text("#!/bin/sh\n")
    (root / "linters").mkdir()
    (root / "linters/.lint-config.json").write_text("{}\n")

    with patch.object(update, "get_asset_path", _fake_get_asset_path(root)):
        assert update._get_asset_sources() == root
        files = update._collect_package_files(root)

    assert ".agents/skills/brainstorming/SKILL.md" in files
    assert ".claude/hooks/pre-push" in files
    assert ".reinicorn/hooks/block-raw-kb-git.sh" in files
    assert "linters/.lint-config.json" in files


def test_get_asset_sources_wheel_layout_returns_data_root(tmp_path: Path):
    """Wheel installs bundle everything as siblings under _data/, where the
    skills dir is `_data/skills` (probe 'skills'). Root must be _data/."""
    from reinicorn.commands import update

    data = tmp_path / "_data"
    (data / "skills" / "brainstorming").mkdir(parents=True)
    (data / "skills/brainstorming/SKILL.md").write_text("x\n")
    (data / "hooks").mkdir()
    (data / "hooks/pre-push").write_text("#!/bin/sh\n")
    (data / "editor-hooks").mkdir()
    (data / "editor-hooks/block-raw-kb-git.sh").write_text("#!/bin/sh\n")

    with patch.object(update, "get_asset_path", _fake_get_asset_path(data)):
        assert update._get_asset_sources() == data
        files = update._collect_package_files(data)

    assert ".agents/skills/brainstorming/SKILL.md" in files
    assert ".claude/hooks/pre-push" in files
    assert ".reinicorn/hooks/block-raw-kb-git.sh" in files
