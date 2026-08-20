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


def _setup_native_only_assets(tmp_path: Path) -> Path:
    """Package assets that no longer ship the 'brainstorming' fork.

    Mirrors the post-fork-removal package: only a native skill is bundled,
    so a manifest entry under .agents/skills/brainstorming/ is a legacy
    vendored fork, not a currently-shipped asset.
    """
    assets = tmp_path / "assets"
    native = assets / "skills" / "using-reinicorn"
    native.mkdir(parents=True)
    (native / "SKILL.md").write_text("# Using Reinicorn\n")
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

    package_files = _collect_package_files(assets, tmp_path)
    assert all("AGENTS.md" not in path for path in package_files)


def test_update_skips_lock_owned_package_files(tmp_path: Path, capsys) -> None:
    """An adapter-installed skill file (recorded in the skillset lock) is
    not `rcorn update`-managed: the sync loop must not copy over it, and
    must not report it via the 'locally modified' skip path (that path
    would misleadingly imply Reinicorn owns and is protecting the file)."""
    from reinicorn.commands.update import cmd_update
    from reinicorn.skillset.lockfile import SkillsetLock, write_lock

    repo = _setup_repo_with_manifest(tmp_path)
    adapter_skill = repo / ".agents" / "skills" / "installed-by-adapter"
    adapter_skill.mkdir(parents=True)
    dest_file = adapter_skill / "SKILL.md"
    dest_file.write_text("# adapter-installed content\n")
    before = dest_file.read_bytes()

    write_lock(
        repo,
        SkillsetLock(
            adapter="superpowers",
            repo="obra/superpowers",
            commit="a" * 40,
            archive_sha256="b" * 64,
            files={"installed-by-adapter/SKILL.md": "irrelevant-hash"},
            wiring={},
        ),
    )

    assets = _setup_package_assets(tmp_path)
    pkg_skill = assets / "skills" / "installed-by-adapter"
    pkg_skill.mkdir(parents=True)
    (pkg_skill / "SKILL.md").write_text("# package version\n")

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update()

    assert rc == 0
    assert dest_file.read_bytes() == before
    out = capsys.readouterr().out
    assert "installed-by-adapter" not in out
    assert "Skipped: 0 files (locally modified)" in out


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


def test_update_honors_configured_skills_dir(tmp_path: Path, capsys) -> None:
    """Native skills are synced to REINICORN_SKILLS_DIR, not `.agents/skills`.

    A hardcoded destination writes a second skills tree the manifest never
    records, so every subsequent run re-reports the same files as "Added".
    """
    from reinicorn.commands.update import cmd_update

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".reinicorn-config").write_text("REINICORN_SKILLS_DIR=custom/skills\n")
    skill = repo / "custom" / "skills" / "using-reinicorn"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Using Reinicorn old\n")
    write_manifest(repo, version="0.1.0")
    assets = _setup_native_only_assets(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        assert cmd_update() == 0

    capsys.readouterr()
    assert (skill / "SKILL.md").read_text() == "# Using Reinicorn\n"
    assert not (repo / ".agents").exists()

    # Everything the package ships is already tracked at the configured
    # destination, so a second run adds nothing.
    with patch("reinicorn.commands.update._get_package_version", return_value="0.3.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        assert cmd_update() == 0

    assert "Added:   0 files" in capsys.readouterr().out


def test_update_already_up_to_date(tmp_path: Path):
    """Same version as manifest → early exit."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    # The legacy-fork migration check runs unconditionally before the
    # version-equality early return, so it needs an asset root — one that
    # still ships 'brainstorming' so this fixture's fork isn't flagged as
    # legacy and the migration prompt (unmocked input here) never fires.
    assets = _setup_package_assets(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.1.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
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
    # Ships 'brainstorming' so the fork-migration check (which also runs in
    # this same-version path) doesn't treat this fixture's fork as legacy
    # and trip the unrelated input() assertion below.
    assets = _setup_package_assets(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.1.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets), \
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

    # 'removed' is not in the legacy-fork inventory, so the migration offer
    # never fires here and this "removed upstream" scenario stands alone.
    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update()

    assert rc == 0
    captured = capsys.readouterr()
    assert "Removed upstream" in captured.out
    assert ".agents/skills/removed/SKILL.md" in captured.out


def test_update_does_not_warn_about_removed_wiring_doc(tmp_path: Path, capsys):
    """The generated skillset wiring doc is never shipped in the package
    (it's rendered locally by `rcorn update`/`rcorn skills`) — it must
    never trigger the generic 'Removed upstream' warning."""
    from reinicorn.commands.update import cmd_update
    from reinicorn.skillset.wiring import wiring_doc_path

    repo = _setup_repo_with_manifest(tmp_path)
    wiring_path = wiring_doc_path(repo)
    wiring_path.parent.mkdir(parents=True, exist_ok=True)
    wiring_path.write_text("# Skillset Wiring\n")
    write_manifest(repo, version="0.1.0")
    # Package assets that (correctly) do not include the generated doc.
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
    assert (
        "Removed upstream: .agents/skills/using-reinicorn/references/skillset-wiring.md"
        not in captured.out
    )


def test_update_cli_dispatch(tmp_path: Path):
    """reins update dispatches to cmd_update."""
    from reinicorn.cli import main

    repo = _setup_repo_with_manifest(tmp_path)
    # Same reasoning as test_update_already_up_to_date: the fork-migration
    # check runs even on the same-version path and needs an asset root.
    assets = _setup_package_assets(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.1.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
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


def test_update_diff_does_not_migrate_submodule_layout(
    submodule_repo: Path, tmp_path: Path
):
    """--diff is read-only: it must not run the submodule-to-clone migration."""
    from reinicorn.commands.update import cmd_update
    from reinicorn.kb_migrate import detect_submodule_layout

    write_manifest(submodule_repo, version="0.1.0")
    assets = _setup_package_assets(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update(diff_target="brainstorming/SKILL.md")

    assert rc == 0
    assert detect_submodule_layout(submodule_repo) is True
    assert (submodule_repo / ".gitmodules").is_file()
    # Still a submodule-style gitfile, not a plain clone's .git directory.
    assert (submodule_repo / "kb" / ".git").is_file()


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
        files = update._collect_package_files(root, tmp_path)

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
        files = update._collect_package_files(data, tmp_path)

    assert ".agents/skills/brainstorming/SKILL.md" in files
    assert ".claude/hooks/pre-push" in files
    assert ".reinicorn/hooks/block-raw-kb-git.sh" in files


# --- Legacy superpowers fork migration -------------------------------------

_MIGRATION_PROMPT_TEXT = (
    "Legacy superpowers skill forks detected (shipped by an older Reinicorn).\n"
    "These are now provided by the 'superpowers' skill-set adapter instead.\n"
    "Migrate now? Installs the adapter (network required) and removes the old\n"
    "copies; locally modified files are kept. Answer 'n' to keep the old forks\n"
    "and never ask again (rcorn skills install superpowers migrates later)."
)


def test_update_migrates_legacy_forks_on_yes(tmp_path: Path) -> None:
    """A legacy fork tracked in the manifest (no skillset lock, and no longer
    shipped by the package) prompts for migration with the exact spec text;
    answering 'y' installs the bundled adapter and deletes the hash-clean
    fork file from disk, and it is never re-added from package assets."""
    from reinicorn.commands.update import cmd_update
    from reinicorn.manifest import sha256_file

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    assets = _setup_native_only_assets(tmp_path)
    fork_file = repo / ".agents" / "skills" / "brainstorming" / "SKILL.md"
    fork_hash = sha256_file(fork_file)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets), \
         patch("reinicorn.commands.update.install_adapter") as mock_install, \
         patch("reinicorn.console.is_interactive", return_value=True), \
         patch("reinicorn.console.confirm", return_value=True) as mock_confirm:
        rc = cmd_update()

    assert rc == 0
    assert mock_confirm.call_args.args[0] == _MIGRATION_PROMPT_TEXT
    assert mock_install.call_count == 1
    adapter_arg, repo_arg = mock_install.call_args.args
    assert adapter_arg.name == "superpowers"
    assert repo_arg == repo
    # The legacy inventory is handed to the installer so the transaction
    # adopts the on-disk forks instead of flagging them as collisions.
    adopt_hashes = mock_install.call_args.kwargs["adopt_hashes"]
    assert adopt_hashes == {"brainstorming/SKILL.md": fork_hash}
    assert not fork_file.is_file()
    assert not fork_file.parent.exists()  # emptied dir pruned

    manifest = json.loads((repo / ".reinicorn/manifest.json").read_text())
    assert ".agents/skills/brainstorming/SKILL.md" not in manifest["files"]


def test_update_migration_preserves_user_authored_skill(tmp_path: Path) -> None:
    """A hand-written skill tracked in the manifest is not a legacy fork.

    The manifest rglobs the whole skills directory, so classifying "any
    tracked skill the package no longer ships" as a legacy superpowers fork
    made the migration delete user-authored skills. Classification is by an
    explicit legacy inventory instead, so this skill survives untouched and
    stays tracked while the real fork beside it is migrated away.
    """
    from reinicorn.commands.update import cmd_update
    from reinicorn.manifest import sha256_file

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    mine = repo / ".agents" / "skills" / "my-skill" / "SKILL.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("# My own skill\n")
    write_manifest(repo, version="0.1.0")  # re-track, now including my-skill
    assets = _setup_native_only_assets(tmp_path)
    fork_file = repo / ".agents" / "skills" / "brainstorming" / "SKILL.md"
    fork_hash = sha256_file(fork_file)

    # Same version on both sides: the "Already up to date" path, so the
    # migration's own manifest rewrite is what the assertions below read.
    with patch("reinicorn.commands.update._get_package_version", return_value="0.1.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets), \
         patch("reinicorn.commands.update.install_adapter") as mock_install, \
         patch("reinicorn.console.is_interactive", return_value=True), \
         patch("reinicorn.console.confirm", return_value=True):
        rc = cmd_update()

    assert rc == 0
    assert mock_install.call_count == 1
    # Only the real fork is handed to the installer for adoption.
    assert mock_install.call_args.kwargs["adopt_hashes"] == {
        "brainstorming/SKILL.md": fork_hash
    }
    assert mine.read_text() == "# My own skill\n"
    assert not fork_file.is_file()

    manifest = json.loads((repo / ".reinicorn/manifest.json").read_text())
    assert ".agents/skills/my-skill/SKILL.md" in manifest["files"]
    assert ".agents/skills/brainstorming/SKILL.md" not in manifest["files"]


def test_update_migration_preserves_locally_modified_fork(
    tmp_path: Path, capsys
) -> None:
    """A legacy fork file whose content diverges from the manifest hash is
    kept on disk and warned about, never deleted, even though migration
    otherwise proceeds (adapter install still runs)."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    assets = _setup_native_only_assets(tmp_path)
    fork_file = repo / ".agents" / "skills" / "brainstorming" / "SKILL.md"
    fork_file.write_text("# Locally modified\n")

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets), \
         patch("reinicorn.commands.update.install_adapter") as mock_install, \
         patch("reinicorn.console.is_interactive", return_value=True), \
         patch("reinicorn.console.confirm", return_value=True):
        rc = cmd_update()

    assert rc == 0
    assert mock_install.call_count == 1
    assert fork_file.is_file()
    assert fork_file.read_text() == "# Locally modified\n"
    captured = capsys.readouterr()
    assert ".agents/skills/brainstorming/SKILL.md" in captured.out
    # The migration's own drift warning fires, but the generic "Removed
    # upstream" loop must not double-flag the same path (the pop-and-
    # rewrite in _maybe_migrate_legacy_forks is what prevents that).
    assert "Removed upstream: .agents/skills/brainstorming/SKILL.md" not in captured.out

    # The target package version differs from the manifest's, so update's
    # ordinary sync flow runs to completion afterwards and its own final
    # write_manifest() recomputes from disk — re-discovering the preserved
    # file (it was never deleted) and tracking its current, drifted hash.
    from reinicorn.manifest import sha256_file

    manifest = json.loads((repo / ".reinicorn/manifest.json").read_text())
    assert (
        manifest["files"][".agents/skills/brainstorming/SKILL.md"]["sha256"]
        == sha256_file(fork_file)
    )


def test_update_migration_skipped_when_lock_present(tmp_path: Path) -> None:
    """A repo that already has a skillset lock is already migrated — the
    fork-migration prompt must never fire."""
    from reinicorn.commands.update import cmd_update
    from reinicorn.skillset.lockfile import SkillsetLock, write_lock

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    assets = _setup_native_only_assets(tmp_path)
    write_lock(
        repo,
        SkillsetLock(
            adapter="superpowers",
            repo="obra/superpowers",
            commit="a" * 40,
            archive_sha256="b" * 64,
            files={},
            wiring={},
        ),
    )

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets), \
         patch("reinicorn.console.is_interactive", return_value=True), \
         patch(
             "reinicorn.console.confirm",
             side_effect=AssertionError("must not prompt"),
         ):
        rc = cmd_update()

    assert rc == 0


def test_update_migration_decline_records_opt_out(tmp_path: Path) -> None:
    """Answering 'n' keeps the forks in place and durably records the
    opt-out via config_set; a later run then skips the prompt entirely."""
    from reinicorn.commands.update import cmd_update
    from reinicorn.config import config_get
    from reinicorn.identity import SKILLSET_MIGRATION_KEY

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    assets = _setup_native_only_assets(tmp_path)
    fork_file = repo / ".agents" / "skills" / "brainstorming" / "SKILL.md"
    before = fork_file.read_bytes()

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets), \
         patch("reinicorn.commands.update.install_adapter") as mock_install, \
         patch("reinicorn.console.is_interactive", return_value=True), \
         patch("reinicorn.console.confirm", return_value=False):
        rc = cmd_update()

    assert rc == 0
    assert mock_install.call_count == 0
    assert fork_file.read_bytes() == before
    assert config_get(SKILLSET_MIGRATION_KEY, root=repo) == "declined"

    # A later run (even a different target version) must not prompt again.
    with patch("reinicorn.commands.update._get_package_version", return_value="0.3.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets), \
         patch("reinicorn.commands.update.install_adapter") as mock_install_2, \
         patch("reinicorn.console.is_interactive", return_value=True), \
         patch(
             "reinicorn.console.confirm",
             side_effect=AssertionError("must not prompt again"),
         ):
        rc2 = cmd_update()

    assert rc2 == 0
    assert mock_install_2.call_count == 0
    assert fork_file.read_bytes() == before


def test_update_migration_skipped_when_non_interactive(tmp_path: Path) -> None:
    """A non-interactive run must neither crash nor answer for the user.

    Agents, CI, and piped stdin cannot see a prompt: offering one there
    either blew up on EOF or banked a permanent "declined" for a question
    nobody was shown. The offer is skipped outright instead, so a later
    interactive run still asks.
    """
    from reinicorn.commands.update import cmd_update
    from reinicorn.config import config_get
    from reinicorn.identity import CONFIG_FILE_NAME, SKILLSET_MIGRATION_KEY

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    assets = _setup_native_only_assets(tmp_path)
    fork_file = repo / ".agents" / "skills" / "brainstorming" / "SKILL.md"
    before = fork_file.read_bytes()

    # No console patches: under pytest neither stdout nor stdin is a tty,
    # which is exactly the non-interactive case under test.
    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets), \
         patch("reinicorn.commands.update.install_adapter") as mock_install:
        rc = cmd_update()

    assert rc == 0
    assert mock_install.call_count == 0
    assert fork_file.read_bytes() == before
    assert not (repo / CONFIG_FILE_NAME).exists()
    assert config_get(SKILLSET_MIGRATION_KEY, root=repo) != "declined"


def test_update_migration_runs_on_same_version(tmp_path: Path) -> None:
    """Migration must run even when the manifest version already equals the
    package version — the 'nothing to sync' early return must not skip the
    one-time legacy-fork offer."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    assets = _setup_native_only_assets(tmp_path)
    fork_file = repo / ".agents" / "skills" / "brainstorming" / "SKILL.md"

    with patch("reinicorn.commands.update._get_package_version", return_value="0.1.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets), \
         patch("reinicorn.commands.update.install_adapter") as mock_install, \
         patch("reinicorn.console.is_interactive", return_value=True), \
         patch("reinicorn.console.confirm", return_value=True):
        rc = cmd_update()

    assert rc == 0
    assert mock_install.call_count == 1
    assert not fork_file.is_file()

    manifest = json.loads((repo / ".reinicorn/manifest.json").read_text())
    assert ".agents/skills/brainstorming/SKILL.md" not in manifest["files"]


def test_update_migration_failure_leaves_forks_and_does_not_record_declined(
    tmp_path: Path, capsys
) -> None:
    """A failed adapter install (e.g. offline) leaves the old forks in
    place, does not record the opt-out (so a later run re-offers), and lets
    the rest of `rcorn update` continue normally rather than aborting."""
    from reinicorn.commands.update import cmd_update
    from reinicorn.config import config_get
    from reinicorn.identity import SKILLSET_MIGRATION_KEY
    from reinicorn.skillset.adapter import AdapterError

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    assets = _setup_native_only_assets(tmp_path)
    fork_file = repo / ".agents" / "skills" / "brainstorming" / "SKILL.md"
    before = fork_file.read_bytes()

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets), \
         patch(
             "reinicorn.commands.update.install_adapter",
             side_effect=AdapterError("offline: could not fetch obra/superpowers"),
         ), \
         patch("reinicorn.console.is_interactive", return_value=True), \
         patch("reinicorn.console.confirm", return_value=True):
        rc = cmd_update()

    assert rc == 0
    assert fork_file.is_file()
    assert fork_file.read_bytes() == before
    assert config_get(SKILLSET_MIGRATION_KEY, root=repo) != "declined"
    captured = capsys.readouterr()
    assert "offline: could not fetch obra/superpowers" in captured.out


# --- Legacy fork migration with the real installer (adoption contract) -----
#
# The tests above mock install_adapter to isolate the prompt/config flow.
# These run the REAL transactional installer (network faked at fetch_source)
# because the migration's core contract — the legacy fork directories are
# still on disk when the installer's collision check runs, and must be
# adopted, not treated as unmanaged collisions — is exactly what a mock
# would hide.

_ADAPTER_COMMIT = "0123456789abcdef0123456789abcdef01234567"
_ADAPTER_SKILL_CONTENT = "# Brainstorming (from the superpowers adapter)\n"


def _setup_bundled_adapter_with_upstream(tmp_path: Path):
    """A synthetic bundled 'superpowers' adapter plus a fake fetch_source.

    The adapter installs a skill named 'brainstorming' — deliberately the
    same name as the legacy fork `_setup_repo_with_manifest` lays down — so
    what's under test is the adoption contract, not superpowers content.
    """
    import shutil
    import tempfile

    upstream = tmp_path / "upstream"
    skill = upstream / "skills" / "brainstorming"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(_ADAPTER_SKILL_CONTENT)

    adapter_dir = tmp_path / "bundled-superpowers"
    adapter_dir.mkdir()
    (adapter_dir / "adapter.yaml").write_text(
        f"""\
name: superpowers
source:
  repo: acme/superpowers
  commit: {_ADAPTER_COMMIT}
  annotation: v1.0.0
skills:
  skills/brainstorming: brainstorming
wiring:
  spec: [brainstorming]
"""
    )

    def fake_fetch(source, cache_dir, *, expected_digest=None):
        parent = Path(tempfile.mkdtemp(prefix="reinicorn-test-fetch-"))
        tree = parent / "tree"
        shutil.copytree(upstream, tree)
        return tree, "c" * 64

    return adapter_dir, fake_fetch


def _migration_patches(repo: Path, assets: Path, adapter_dir: Path, fake_fetch):
    """The patch stack every real-installer migration test shares."""
    return [
        patch("reinicorn.commands.update._get_package_version", return_value="0.1.0"),
        patch("reinicorn.commands.update._get_repo_root", return_value=repo),
        patch("reinicorn.commands.update._get_asset_sources", return_value=assets),
        patch(
            "reinicorn.commands.update.get_asset_path",
            lambda name: adapter_dir if name == "adapters/superpowers" else None,
        ),
        patch("reinicorn.skillset.installer.fetch_source", fake_fetch),
        patch("reinicorn.console.is_interactive", return_value=True),
        patch("reinicorn.console.confirm", return_value=True),
    ]


def test_update_migration_with_real_installer_adopts_clean_forks(
    tmp_path: Path, capsys
) -> None:
    """The forks are still on disk when the installer runs — they must be
    adopted (replaced inside the transaction), never flagged as unmanaged
    collisions. A legacy file the adapter does not produce is cleaned up
    post-install when hash-clean; the manifest drops all migrated entries."""
    from contextlib import ExitStack

    from reinicorn.commands.update import cmd_update
    from reinicorn.skillset.lockfile import read_lock

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    # A second legacy skill with no adapter counterpart: 'update-superpowers'
    # is in the legacy inventory (a pre-adapter Reinicorn shipped it) but no
    # adapter installs it, so it must be cleaned up post-install.
    oldskill = repo / ".agents" / "skills" / "update-superpowers"
    oldskill.mkdir(parents=True)
    (oldskill / "SKILL.md").write_text("# Old skill\n")
    write_manifest(repo, version="0.1.0")  # re-track, now including it
    assets = _setup_native_only_assets(tmp_path)
    adapter_dir, fake_fetch = _setup_bundled_adapter_with_upstream(tmp_path)
    fork_file = repo / ".agents" / "skills" / "brainstorming" / "SKILL.md"

    with ExitStack() as stack:
        for p in _migration_patches(repo, assets, adapter_dir, fake_fetch):
            stack.enter_context(p)
        rc = cmd_update()

    assert rc == 0
    out = capsys.readouterr().out
    assert "already exists" not in out  # no collision abort
    assert "migration failed" not in out.lower()
    assert "Migrated legacy superpowers forks" in out
    # Hash-clean fork replaced by the adapter's copy inside the transaction.
    assert fork_file.read_text() == _ADAPTER_SKILL_CONTENT
    # Legacy file with no adapter counterpart: hash-clean → deleted + pruned.
    assert not oldskill.exists()
    lock = read_lock(repo)
    assert lock is not None
    assert lock.adapter == "superpowers"
    assert set(lock.files) == {"brainstorming/SKILL.md"}
    manifest = json.loads((repo / ".reinicorn/manifest.json").read_text())
    assert ".agents/skills/brainstorming/SKILL.md" not in manifest["files"]
    assert ".agents/skills/update-superpowers/SKILL.md" not in manifest["files"]


def test_update_migration_with_real_installer_preserves_drifted_fork(
    tmp_path: Path, capsys
) -> None:
    """A locally modified fork the adapter produces is kept verbatim by the
    transaction, warned about by name, and the lock records the adapter's
    INTENDED hash so the next 'rcorn skills update' sees a local edit."""
    import hashlib
    from contextlib import ExitStack

    from reinicorn.commands.update import cmd_update
    from reinicorn.skillset.lockfile import read_lock

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    assets = _setup_native_only_assets(tmp_path)
    adapter_dir, fake_fetch = _setup_bundled_adapter_with_upstream(tmp_path)
    fork_file = repo / ".agents" / "skills" / "brainstorming" / "SKILL.md"
    fork_file.write_text("# My local edits\n")  # drift after manifest recorded it

    with ExitStack() as stack:
        for p in _migration_patches(repo, assets, adapter_dir, fake_fetch):
            stack.enter_context(p)
        rc = cmd_update()

    assert rc == 0
    out = capsys.readouterr().out
    assert "migration failed" not in out.lower()
    assert fork_file.read_text() == "# My local edits\n"
    assert "brainstorming/SKILL.md" in out
    assert "rcorn skills update --force" in out
    lock = read_lock(repo)
    assert lock is not None
    assert lock.files["brainstorming/SKILL.md"] == hashlib.sha256(
        _ADAPTER_SKILL_CONTENT.encode()
    ).hexdigest()
    manifest = json.loads((repo / ".reinicorn/manifest.json").read_text())
    assert ".agents/skills/brainstorming/SKILL.md" not in manifest["files"]


def test_update_migration_with_real_installer_rolls_back_on_failure(
    tmp_path: Path, capsys
) -> None:
    """A mid-transaction failure restores the legacy forks byte for byte,
    writes no lock, keeps the manifest entries, and lets 'rcorn update'
    finish normally so the next run re-offers the migration."""
    from contextlib import ExitStack

    from reinicorn.commands.update import cmd_update
    from reinicorn.skillset.lockfile import read_lock

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    assets = _setup_native_only_assets(tmp_path)
    adapter_dir, fake_fetch = _setup_bundled_adapter_with_upstream(tmp_path)
    fork_file = repo / ".agents" / "skills" / "brainstorming" / "SKILL.md"
    before = fork_file.read_bytes()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    with ExitStack() as stack:
        for p in _migration_patches(repo, assets, adapter_dir, fake_fetch):
            stack.enter_context(p)
        stack.enter_context(
            patch("reinicorn.skillset.installer.write_lock", boom)
        )
        rc = cmd_update()

    assert rc == 0  # migration failure never aborts the rest of update
    assert fork_file.read_bytes() == before  # rollback restored the fork
    assert read_lock(repo) is None
    manifest = json.loads((repo / ".reinicorn/manifest.json").read_text())
    assert ".agents/skills/brainstorming/SKILL.md" in manifest["files"]
    assert "migration failed" in capsys.readouterr().out.lower()


def _wiring_doc_path(repo: Path) -> Path:
    return repo / ".agents/skills/using-reinicorn/references/skillset-wiring.md"


def test_update_regenerates_wiring_doc_without_lock(tmp_path: Path) -> None:
    """No skillset lock installed → the doc still exists after update, with
    every row's skills cell rendered registry-only (em dash)."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path)
    assets = _setup_package_assets(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update()

    assert rc == 0
    doc = _wiring_doc_path(repo)
    assert doc.is_file()
    content = doc.read_text()
    rows = [line for line in content.splitlines() if line.startswith("| ")][1:]
    assert rows  # sanity: header row is skipped, data rows remain
    assert all(row.endswith("| — |") for row in rows)


def test_update_regenerates_wiring_doc_with_lock(tmp_path: Path) -> None:
    """A skillset lock's wiring populates the doc's skills column."""
    from reinicorn.commands.update import cmd_update
    from reinicorn.skillset.adapter import WiringEntry
    from reinicorn.skillset.lockfile import SkillsetLock, write_lock

    repo = _setup_repo_with_manifest(tmp_path)
    assets = _setup_package_assets(tmp_path)
    write_lock(
        repo,
        SkillsetLock(
            adapter="superpowers",
            repo="obra/superpowers",
            commit="a" * 40,
            archive_sha256="b" * 64,
            files={},
            wiring={"spec": WiringEntry(skills=("alpha",))},
        ),
    )

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update()

    assert rc == 0
    content = _wiring_doc_path(repo).read_text()
    spec_row = next(
        line for line in content.splitlines() if line.startswith("| spec |")
    )
    assert "alpha" in spec_row


def test_update_regenerates_wiring_doc_when_already_up_to_date(
    tmp_path: Path,
) -> None:
    """The 'Already up to date' early return is a successful exit path too —
    a fresh or migrated checkout must still get the doc."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path, version="0.1.0")
    assets = _setup_package_assets(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.1.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update()

    assert rc == 0
    assert _wiring_doc_path(repo).is_file()


def test_update_diff_mode_does_not_write_wiring_doc(tmp_path: Path) -> None:
    """--diff is read-only: it must not regenerate the wiring doc."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path)
    assets = _setup_package_assets(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets):
        rc = cmd_update(diff_target="brainstorming/SKILL.md")

    assert rc == 0
    assert not _wiring_doc_path(repo).exists()


def test_update_wiring_write_failure_warns_and_continues(
    tmp_path: Path, capsys
) -> None:
    """A wiring-doc write failure (e.g. unwritable dir) must not crash
    update — warn and let the rest of the sync proceed normally."""
    from reinicorn.commands.update import cmd_update

    repo = _setup_repo_with_manifest(tmp_path)
    assets = _setup_package_assets(tmp_path)

    with patch("reinicorn.commands.update._get_package_version", return_value="0.2.0"), \
         patch("reinicorn.commands.update._get_repo_root", return_value=repo), \
         patch("reinicorn.commands.update._get_asset_sources", return_value=assets), \
         patch(
             "reinicorn.commands.update.write_wiring",
             side_effect=OSError("disk full"),
         ):
        rc = cmd_update()

    assert rc == 0
    captured = capsys.readouterr()
    assert "wiring" in captured.out.lower()
    assert "disk full" in captured.out
    # The rest of the sync still ran normally.
    assert (repo / ".agents/skills/brainstorming/SKILL.md").read_text() == "# Brainstorming v2\n"
