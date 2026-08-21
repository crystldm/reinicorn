"""Restore adapter-installed skill files from the skillset lockfile.

The lockfile (`.reinicorn/skillset-lock.json`) is the committed record of
which adapter a project uses and exactly which files it produced. The
installed skill files themselves may be gitignored — reinicorn's own repo
treats them that way — so a fresh clone or a new linked worktree starts
with a lock and no files, and `using-reinicorn`'s wiring doc points at
skills that are not there.

This module is the one seam that repairs that state. `rcorn skills
install` with no argument, `rcorn update`, the hooks-only `rcorn init`
path, and the post-checkout hook all route through `ensure_adapter_files`;
nothing else writes adapter files outside the installer's transaction.

Restore is deliberately narrower than `update_adapter`: it writes only the
files the lock records and the disk lacks, each verified to hash exactly
as the lock says, and never touches a path that exists — a locally edited
sibling must neither block the restore nor be clobbered by it. A lock
whose record no longer matches what the adapter stages is an update, not a
restore, and is refused as such.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import replace
from enum import Enum
from pathlib import Path

from reinicorn import console
from reinicorn.assets import get_asset_path
from reinicorn.config import skills_dir
from reinicorn.skillset.adapter import Adapter, AdapterError, load_adapter
from reinicorn.skillset.engine import build_staging
from reinicorn.skillset.fetch import default_cache_dir, fetch_source
from reinicorn.skillset.installer import maintain_link
from reinicorn.skillset.lockfile import SKILLSET_LOCK_PATH, SkillsetLock, read_lock
from reinicorn.skillset.wiring import write_wiring


class RestoreOutcome(Enum):
    """What `ensure_adapter_files` found and did."""

    NO_LOCK = "no-lock"  # nothing recorded, nothing to restore
    COMPLETE = "complete"  # lock present, every recorded file on disk
    RESTORED = "restored"  # files were missing and are back
    FAILED = "failed"  # restore was attempted, reported, and left as-is


def resolve_adapter_dir(name_or_path: str) -> Path | None:
    """An existing directory path wins; otherwise a bundled adapter by name."""
    candidate = Path(name_or_path)
    if candidate.is_dir():
        return candidate
    return get_asset_path(f"adapters/{name_or_path}")


def locked_adapter(lock: SkillsetLock) -> Adapter:
    """Re-resolve the lock's adapter, re-pinned to the lock's commit.

    The lockfile records only the adapter's name, so a bundled adapter or a
    cwd-relative directory of that name is all that can be re-resolved; a
    local-path adapter installed from elsewhere raises `AdapterError`. The
    annotation is kept only while the adapter definition still pins the
    same commit the lock does — otherwise it would describe the wrong pin.
    """
    adapter_dir = resolve_adapter_dir(lock.adapter)
    if adapter_dir is None:
        raise AdapterError(
            f"Adapter '{lock.adapter}' is not a bundled adapter, and no "
            f"directory named '{lock.adapter}' was found here.\n"
            f"  Reinicorn cannot re-resolve a local-path adapter's source "
            f"automatically — the lockfile only records its name.\n"
            f"  How to fix: run 'rcorn skills install <path-to-{lock.adapter}>' "
            f"again to update it."
        )
    adapter = load_adapter(adapter_dir)
    annotation = (
        adapter.source.annotation if adapter.source.commit == lock.commit else ""
    )
    return replace(
        adapter,
        source=replace(adapter.source, commit=lock.commit, annotation=annotation),
    )


def missing_files(repo_root: Path, lock: SkillsetLock) -> list[str]:
    """Lock-recorded paths (skills-dir-relative) with nothing on disk, sorted.

    Anything at the path — a file, a directory, even a dangling symlink —
    counts as present: whatever someone put there is theirs, and restore
    never replaces it.
    """
    skills_root = repo_root / skills_dir(repo_root)
    return sorted(
        rel
        for rel in lock.files
        if not (skills_root / rel).exists() and not (skills_root / rel).is_symlink()
    )


def restore_from_lock(
    repo_root: Path, lock: SkillsetLock, *, cache_dir: Path | None = None
) -> list[str]:
    """Write back every lock-recorded file missing from disk; return those paths.

    Fetches the lock's pinned source (digest-checked against the lock),
    rebuilds the adapter's staging tree, and copies only the missing files.
    Also regenerates the wiring doc and the compatibility link, which a
    fresh clone lacks for the same reason. The lock itself is never
    rewritten — it is the record being restored from. Raises `AdapterError`.
    """
    missing = missing_files(repo_root, lock)
    if not missing:
        return []

    adapter = locked_adapter(lock)
    if adapter.source.repo != lock.repo:
        raise AdapterError(
            f"Adapter '{lock.adapter}': {repo_root / SKILLSET_LOCK_PATH} records "
            f"source {lock.repo}, but the adapter definition now names "
            f"{adapter.source.repo}.\n"
            f"  Restoring would fetch from a source the lock never recorded.\n"
            f"  How to fix: run 'rcorn skills update' to re-pin the lock to "
            f"the adapter's current source."
        )

    skills_root = repo_root / skills_dir(repo_root)
    cache = cache_dir if cache_dir is not None else default_cache_dir()
    work = Path(tempfile.mkdtemp(prefix="reinicorn-skillset-restore-"))
    try:
        tree, _digest = fetch_source(
            adapter.source, cache, expected_digest=lock.archive_sha256
        )
        try:
            hashes = build_staging(adapter, tree, work / "staging")
        finally:
            shutil.rmtree(tree.parent, ignore_errors=True)

        stale = [rel for rel in missing if hashes.get(rel) != lock.files[rel]]
        if stale:
            listing = "".join(f"    {rel}\n" for rel in stale)
            raise AdapterError(
                f"Adapter '{lock.adapter}': {repo_root / SKILLSET_LOCK_PATH} is "
                f"out of date with the adapter definition — these missing "
                f"files would not restore to what the lock recorded:\n"
                f"{listing}"
                f"  Nothing was restored.\n"
                f"  How to fix: run 'rcorn skills update' to re-apply the "
                f"adapter and refresh the lock."
            )

        try:
            for rel in missing:
                target = skills_root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(work / "staging" / rel, target)
        except OSError as exc:
            raise AdapterError(
                f"Adapter '{lock.adapter}': failed while restoring into "
                f"{skills_root} ({exc}).\n"
                f"  Files restored before the failure are in place; the rest "
                f"are still missing.\n"
                f"  How to fix: check the permissions and free space on "
                f"{repo_root}, then re-run 'rcorn skills install'."
            ) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)

    write_wiring(repo_root, lock.wiring)
    maintain_link(repo_root)
    return missing


def ensure_adapter_files(
    repo_root: Path, *, cache_dir: Path | None = None
) -> RestoreOutcome:
    """Restore whatever the lock records and the disk lacks; report, never raise.

    Silent when there is no lock or nothing is missing, so the callers that
    run on every `rcorn update`, `rcorn init`, and checkout add no noise to
    the common case. A failed restore is reported with its cause and the
    command that retries it; the caller carries on — missing skill files
    are recoverable, a failed checkout or update is disruptive.
    """
    lock = read_lock(repo_root)
    if lock is None:
        return RestoreOutcome.NO_LOCK
    missing = missing_files(repo_root, lock)
    if not missing:
        return RestoreOutcome.COMPLETE

    console.info(
        f"{len(missing)} skill file(s) recorded in {SKILLSET_LOCK_PATH} are "
        f"missing — restoring '{lock.adapter}' @ {lock.commit[:12]}."
    )
    try:
        restored = restore_from_lock(repo_root, lock, cache_dir=cache_dir)
    except AdapterError as exc:
        console.warn(
            f"Could not restore the '{lock.adapter}' skill files: {exc}\n"
            f"  How to fix: resolve the cause above, then run "
            f"'rcorn skills install' (no argument) to retry."
        )
        return RestoreOutcome.FAILED
    console.success(f"Restored {len(restored)} '{lock.adapter}' skill file(s).")
    return RestoreOutcome.RESTORED
