"""Skillset lockfile: persisted record of the installed adapter.

Tracks which adapter is installed, its pin (repo/commit/archive hash), a
per-file sha256 baseline (so `rcorn skills update` can detect local edits the
same way `reinicorn.manifest` does for other managed assets), and the wiring
map. Wiring is persisted here — not re-read from the adapter directory — so
`update`/`init` can re-render the wiring doc without needing the adapter
source again; local-path adapters aren't resolvable later.

`read_lock` is the only place lockfile shape is checked; everything
downstream trusts the typed `SkillsetLock` object (golden principle 1:
validate at boundaries). This mirrors `read_manifest` in `reinicorn.manifest`:
a missing lock means "no adapter installed" (no warning), while a corrupt or
misshapen lock means Reinicorn's own bookkeeping is untrustworthy (warn via
the module logger, then behave as if nothing were installed).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from reinicorn.identity import SKILLSET_LOCK_FILE_NAME, STATE_DIR_NAME
from reinicorn.skillset.adapter import WiringEntry

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

SKILLSET_LOCK_PATH = f"{STATE_DIR_NAME}/{SKILLSET_LOCK_FILE_NAME}"

_REQUIRED_KEYS = {"adapter", "repo", "commit", "archive_sha256", "files", "wiring"}


@dataclass(frozen=True)
class SkillsetLock:
    adapter: str
    repo: str
    commit: str
    archive_sha256: str
    files: dict[str, str]  # skills-dir-relative path -> sha256
    wiring: dict[str, WiringEntry]


def write_lock(repo_root: Path, lock: SkillsetLock) -> Path:
    """Persist *lock* to `<repo_root>/.reinicorn/skillset-lock.json`."""
    lock_dir = repo_root / STATE_DIR_NAME
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / SKILLSET_LOCK_FILE_NAME
    data = {
        "adapter": lock.adapter,
        "repo": lock.repo,
        "commit": lock.commit,
        "archive_sha256": lock.archive_sha256,
        "files": lock.files,
        "wiring": {
            doc_type: {"skills": list(entry.skills), "optional": entry.optional}
            for doc_type, entry in lock.wiring.items()
        },
    }
    lock_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return lock_path


def read_lock(repo_root: Path) -> SkillsetLock | None:
    """Read and validate the skillset lockfile.

    Returns None if the file is missing, malformed, or has an invalid shape.
    A missing lock is a normal state (no adapter installed) and is not
    warned about; anything present but corrupt or misshapen is, since it
    means Reinicorn's own state is untrustworthy.
    """
    lock_path = repo_root / STATE_DIR_NAME / SKILLSET_LOCK_FILE_NAME
    if not lock_path.is_file():
        return None

    try:
        data = json.loads(lock_path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupt skillset lock at %s", lock_path)
        return None

    if not isinstance(data, dict) or not _REQUIRED_KEYS.issubset(data):
        logger.warning("Skillset lock missing required keys at %s", lock_path)
        return None

    if not (
        isinstance(data["adapter"], str)
        and isinstance(data["repo"], str)
        and isinstance(data["commit"], str)
        and isinstance(data["archive_sha256"], str)
    ):
        logger.warning("Skillset lock has invalid field types at %s", lock_path)
        return None

    files = _read_files(data["files"])
    if files is None:
        logger.warning("Skillset lock has invalid 'files' shape at %s", lock_path)
        return None

    wiring = _read_wiring(data["wiring"])
    if wiring is None:
        logger.warning("Skillset lock has invalid 'wiring' shape at %s", lock_path)
        return None

    return SkillsetLock(
        adapter=data["adapter"],
        repo=data["repo"],
        commit=data["commit"],
        archive_sha256=data["archive_sha256"],
        files=files,
        wiring=wiring,
    )


def _read_files(value: Any) -> dict[str, str] | None:
    """Validate the 'files' mapping: skills-dir-relative path -> sha256, both str."""
    if not isinstance(value, dict):
        return None
    for path, digest in value.items():
        if not isinstance(path, str) or not isinstance(digest, str):
            return None
    return dict(value)


def _read_wiring(value: Any) -> dict[str, WiringEntry] | None:
    """Validate and deserialize the 'wiring' mapping into WiringEntry objects."""
    if not isinstance(value, dict):
        return None
    result: dict[str, WiringEntry] = {}
    for doc_type, entry in value.items():
        if not isinstance(doc_type, str) or not isinstance(entry, dict):
            return None
        skills = entry.get("skills")
        if not isinstance(skills, list) or not all(
            isinstance(s, str) for s in skills
        ):
            return None
        optional = entry.get("optional", False)
        if not isinstance(optional, bool):
            return None
        result[doc_type] = WiringEntry(skills=tuple(skills), optional=optional)
    return result
