"""Tests for manifest read/write."""

from __future__ import annotations

import json
from pathlib import Path

from reinicorn.manifest import MANAGED_ASSETS, read_manifest, write_manifest


def test_agents_is_not_a_managed_asset() -> None:
    assert "AGENTS.md" not in MANAGED_ASSETS


def test_editor_hooks_are_managed() -> None:
    """Editor hooks live under .reinicorn/hooks and must be tracked so
    'rcorn update' can sync them and protect local modifications."""
    assert ".reinicorn/hooks" in MANAGED_ASSETS


def test_write_manifest_tracks_editor_hooks(tmp_path: Path):
    """Files under .reinicorn/hooks are recorded in the manifest."""
    repo = tmp_path / "repo"
    hooks = repo / ".reinicorn" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "block-raw-kb-git.sh").write_text("#!/bin/sh\n")

    write_manifest(repo, version="0.1.0")

    data = json.loads((repo / ".reinicorn" / "manifest.json").read_text())
    assert ".reinicorn/hooks/block-raw-kb-git.sh" in data["files"]


def test_write_manifest_creates_file(tmp_path: Path):
    """write_manifest creates .reinicorn/manifest.json with checksums."""
    repo = tmp_path / "repo"
    repo.mkdir()
    skills = repo / ".agents" / "skills" / "brainstorming"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# Brainstorming\n")
    (repo / "AGENTS.md").write_text("# Agents\n")

    write_manifest(repo, version="0.1.0")

    manifest_path = repo / ".reinicorn" / "manifest.json"
    assert manifest_path.is_file()
    data = json.loads(manifest_path.read_text())
    assert data["reinicorn_version"] == "0.1.0"
    assert "installed_at" in data
    assert ".agents/skills/brainstorming/SKILL.md" in data["files"]
    assert "AGENTS.md" not in data["files"]


def test_read_manifest_returns_data(tmp_path: Path):
    """read_manifest returns parsed manifest data."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("# Agents\n")
    write_manifest(repo, version="0.1.0")

    data = read_manifest(repo)
    assert data is not None
    assert data["reinicorn_version"] == "0.1.0"
    assert "AGENTS.md" not in data["files"]


def test_read_manifest_returns_none_when_missing(tmp_path: Path):
    """read_manifest returns None when no manifest exists."""
    data = read_manifest(tmp_path)
    assert data is None


def test_read_manifest_returns_none_for_invalid_json(tmp_path: Path):
    """read_manifest returns None when manifest is corrupted."""
    manifest_dir = tmp_path / ".reinicorn"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.json").write_text("not json")
    data = read_manifest(tmp_path)
    assert data is None


def test_read_manifest_returns_none_for_missing_keys(tmp_path: Path):
    """read_manifest returns None when required keys are missing."""
    manifest_dir = tmp_path / ".reinicorn"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.json").write_text('{"foo": "bar"}')
    data = read_manifest(tmp_path)
    assert data is None
