"""Manifest for tracking installed Reinicorn assets."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from reinicorn.identity import MANIFEST_FILE_NAME, STATE_DIR_NAME

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

MANIFEST_PATH = f"{STATE_DIR_NAME}/{MANIFEST_FILE_NAME}"

# Asset directories/files managed by Reinicorn
MANAGED_ASSETS = [
    ".agents/skills",
    ".claude/hooks",
    ".reinicorn/hooks",
    "linters",
]

_REQUIRED_KEYS = {"reinicorn_version", "files"}


def sha256_file(path: Path) -> str:
    """Return hex SHA-256 digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _collect_files(repo_root: Path) -> dict[str, dict[str, str]]:
    """Collect checksums for all managed asset files."""
    files: dict[str, dict[str, str]] = {}
    for asset in MANAGED_ASSETS:
        asset_path = repo_root / asset
        if asset_path.is_file():
            rel = str(asset_path.relative_to(repo_root))
            files[rel] = {"sha256": sha256_file(asset_path)}
        elif asset_path.is_dir():
            for f in sorted(asset_path.rglob("*")):
                if f.is_file():
                    rel = str(f.relative_to(repo_root))
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
