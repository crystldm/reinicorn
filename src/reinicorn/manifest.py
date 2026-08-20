"""Manifest for tracking installed Reinicorn assets."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from reinicorn.config import skills_dir
from reinicorn.identity import MANIFEST_FILE_NAME, STATE_DIR_NAME

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

MANIFEST_PATH = f"{STATE_DIR_NAME}/{MANIFEST_FILE_NAME}"

# Asset directories/files managed by Reinicorn, at their fixed repo-root-
# relative location. The native-skill destination is NOT fixed — it honors
# `REINICORN_SKILLS_DIR` — so it is resolved per repo_root in
# `_managed_asset_paths` instead of hardcoded here.
MANAGED_ASSETS = [
    ".claude/hooks",
    ".reinicorn/hooks",
    "linters",
]


def _managed_asset_paths(repo_root: Path) -> list[str]:
    """`MANAGED_ASSETS` plus the configured native-skill destination.

    Kept out of the module-level constant because it depends on
    *repo_root* (`skills_dir` reads `REINICORN_SKILLS_DIR` from the repo's
    config) — everything else in `MANAGED_ASSETS` is a fixed path.
    """
    return [skills_dir(repo_root).as_posix(), *MANAGED_ASSETS]


_REQUIRED_KEYS = {"reinicorn_version", "files"}


def sha256_file(path: Path) -> str:
    """Return hex SHA-256 digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lock_owned_paths(repo_root: Path) -> set[str]:
    """Repo-root-relative paths owned by an installed skill-set adapter.

    Adapter-installed files (tracked in `.reinicorn/skillset-lock.json`,
    skills-dir-relative) are `rcorn skills`-managed, not `rcorn
    update`-managed — they must never appear in the asset manifest. Reads
    the lock lazily and tolerates its absence: no lock means no adapter is
    installed, so nothing is excluded. `read_lock` is imported here, not at
    module top, for the same reason `_generated_paths` lazily imports
    `wiring`: avoid a needless import-time dependency on the skillset
    package (and its `yaml` import) for callers that never touch it.
    """
    from reinicorn.skillset.lockfile import read_lock

    lock = read_lock(repo_root)
    if lock is None:
        return set()
    skl_dir = skills_dir(repo_root)
    return {(skl_dir / rel).as_posix() for rel in lock.files}


def _generated_paths(repo_root: Path) -> set[str]:
    """Repo-root-relative paths of files Reinicorn generates itself.

    The skillset wiring doc lives under the configured skills dir (a
    managed asset destination — see `_managed_asset_paths`) but is
    rendered locally by `rcorn update`/`rcorn skills` from the doc-type
    registry — it is marked generated in the asset manifest, not shipped
    by the package. It is also not lock-owned (`using-reinicorn` is
    native, not adapter-installed), so `_lock_owned_paths` alone wouldn't
    exclude it. Lazily imported to avoid a needless import-time dependency
    on the skillset package for callers that never touch it.

    An absolute `REINICORN_SKILLS_DIR` can put the doc outside repo_root
    entirely; there is nothing under repo_root to exclude in that case, so
    this returns empty rather than raising.
    """
    from reinicorn.skillset.wiring import wiring_doc_path

    doc = wiring_doc_path(repo_root)
    if not doc.is_relative_to(repo_root):
        return set()
    return {doc.relative_to(repo_root).as_posix()}


def _collect_files(repo_root: Path) -> dict[str, dict[str, str]]:
    """Collect checksums for all managed asset files.

    Skips any path owned by an installed skill-set adapter (see
    `_lock_owned_paths`) and any Reinicorn-generated path (see
    `_generated_paths`) — neither is a Reinicorn-managed *shipped* asset.
    """
    excluded = _lock_owned_paths(repo_root) | _generated_paths(repo_root)
    files: dict[str, dict[str, str]] = {}
    for asset in _managed_asset_paths(repo_root):
        asset_path = repo_root / asset
        if not asset_path.is_relative_to(repo_root):
            continue  # e.g. an absolute REINICORN_SKILLS_DIR outside the repo
        if asset_path.is_file():
            rel = asset_path.relative_to(repo_root).as_posix()
            if rel in excluded:
                continue
            files[rel] = {"sha256": sha256_file(asset_path)}
        elif asset_path.is_dir():
            for f in sorted(asset_path.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(repo_root).as_posix()
                    if rel in excluded:
                        continue
                    files[rel] = {"sha256": sha256_file(f)}
    return files


def write_manifest(repo_root: Path, *, version: str) -> Path:
    """Write the Reinicorn manifest with current asset checksums."""
    data = {
        "reinicorn_version": version,
        "installed_at": datetime.now(UTC).isoformat(),
        "files": _collect_files(repo_root),
    }
    return write_manifest_data(repo_root, data)


def write_manifest_data(repo_root: Path, data: dict) -> Path:
    """Persist validated manifest data without recalculating asset baselines."""
    manifest_dir = repo_root / STATE_DIR_NAME
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / MANIFEST_FILE_NAME
    manifest_path.write_text(json.dumps(data, indent=2) + "\n")
    return manifest_path


def read_manifest(repo_root: Path) -> dict | None:
    """Read and validate the Reinicorn manifest.

    Returns None if the file is missing, malformed, or missing required keys.
    Validation happens here at the boundary so callers can trust the shape.
    """
    manifest_path = repo_root / STATE_DIR_NAME / MANIFEST_FILE_NAME
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupt manifest at %s", manifest_path)
        return None
    if not isinstance(data, dict) or not _REQUIRED_KEYS.issubset(data):
        logger.warning("Manifest missing required keys at %s", manifest_path)
        return None
    return data
