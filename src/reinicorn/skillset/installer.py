"""Transactional adapter installer: all-or-nothing installs, updates, and link."""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from reinicorn import console
from reinicorn.config import skills_dir, skills_link
from reinicorn.manifest import read_manifest, sha256_file
from reinicorn.skillset.adapter import AdapterError
from reinicorn.skillset.engine import build_staging, validate_patch_targets
from reinicorn.skillset.fetch import default_cache_dir, fetch_source
from reinicorn.skillset.lockfile import (
    SKILLSET_LOCK_PATH,
    SkillsetLock,
    read_lock,
    write_lock,
)
from reinicorn.skillset.wiring import render_wiring, wiring_doc_path, write_wiring

if TYPE_CHECKING:
    from reinicorn.skillset.adapter import Adapter


def _stale_symlink_target(link: Path, skills: Path) -> str | None:
    """The link's current raw target, if it differs from the target
    `skills` currently resolves to — else None (also None when *link*
    isn't a symlink).

    Compared as the raw `readlink()` string against the relative target
    `maintain_link` would create, not resolved filesystem paths, so this
    works even when `skills` doesn't exist yet.
    """
    if not link.is_symlink():
        return None
    expected = os.path.relpath(skills, link.parent)
    current = str(link.readlink())
    return None if current == expected else current


def maintain_link(repo_root: Path) -> None:
    """Point the configured compatibility link at the configured skills dir.

    Claude Code only reads `.claude/skills`; Codex/Cursor/Copilot read
    `.agents/skills` natively, so the link keeps one canonical tree readable
    by both. A pre-existing REAL link directory is left untouched (never
    delete user content) — warn instead; a platform without symlinks gets a
    copy plus a warning; `REINICORN_SKILLS_LINK=none` disables the link. An
    existing symlink that no longer points at the configured skills dir
    (e.g. REINICORN_SKILLS_DIR changed, or a stale checkout) is relinked —
    only a REAL directory is left alone, never a stale link.

    Every path this can mutate is mirrored by `_commit`'s link-tracking
    predicate — keep the two in lockstep (see the comment there).
    """
    link_rel = skills_link(repo_root)
    if link_rel is None:
        return

    skills_rel = skills_dir(repo_root)
    link = repo_root / link_rel
    skills = repo_root / skills_rel

    stale_target = _stale_symlink_target(link, skills)
    if link.is_symlink():
        if stale_target is None:
            return  # already linked correctly
        console.warn(
            f"{link_rel.as_posix()} was a stale link (-> {stale_target}) — "
            f"relinking it to {skills_rel.as_posix()}/."
        )
        link.unlink()
    elif link.is_dir():
        console.warn(
            f"{link_rel.as_posix()} already exists as a real directory — "
            f"left in place.\n"
            f"  It is not managed by Reinicorn and may be stale. Canonical\n"
            f"  skills now live in {skills_rel.as_posix()}/ — remove "
            f"{link_rel.as_posix()} and\n"
            f"  re-run 'rcorn update' to get a live symlink."
        )
        return
    if not skills.is_dir():
        # Linking to a missing target would leave a dangling symlink (and the
        # copy fallback would fail outright).
        console.warn(
            f"Skills directory {skills_rel.as_posix()}/ does not exist — "
            f"skipped the\n"
            f"  {link_rel.as_posix()} link.\n"
            f"  How to fix: create {skills_rel.as_posix()}/ (or point "
            f"REINICORN_SKILLS_DIR at the\n"
            f"  directory that holds your skills), then re-run 'rcorn init'."
        )
        return

    link.parent.mkdir(parents=True, exist_ok=True)
    # Relative so the link survives the repo being moved or cloned elsewhere.
    rel_target = os.path.relpath(skills, link.parent)
    try:
        link.symlink_to(rel_target, target_is_directory=True)
        console.success(f"Linked {link_rel.as_posix()} -> {skills_rel.as_posix()}")
    except OSError:
        shutil.copytree(skills, link, dirs_exist_ok=True)
        console.warn(
            f"Symlinks unavailable (Windows without developer mode?) — copied\n"
            f"  skills to {link_rel.as_posix()} instead. This copy is NOT "
            f"auto-synced;\n"
            f"  re-run 'rcorn init' after each 'rcorn update' to refresh it."
        )


def install_adapter(
    adapter: Adapter, repo_root: Path, *, cache_dir: Path | None = None
) -> None:
    """Install *adapter* into *repo_root* as one transaction.

    Fetch the pinned upstream tree, build the staging tree, refuse to
    overwrite anything Reinicorn does not own, then commit skill files, the
    lockfile, the wiring doc, and the compatibility link together. Any
    failure restores the project exactly as it was. Re-installing the same
    adapter is a controlled replacement driven by the lockfile inventory
    (identical to `update_adapter` without `force`). Raises `AdapterError`.
    """
    lock = read_lock(repo_root)
    if lock is not None and lock.adapter != adapter.name:
        raise AdapterError(
            f"Adapter '{adapter.name}': project {repo_root} already has adapter "
            f"'{lock.adapter}' installed (per {repo_root / SKILLSET_LOCK_PATH}).\n"
            f"  Reinicorn tracks one adapter per project — installing a second "
            f"one would leave '{lock.adapter}'s files unowned.\n"
            f"  How to fix: update or remove '{lock.adapter}' first, or install "
            f"'{adapter.name}' into a different project."
        )
    _install_or_update(adapter, repo_root, lock=lock, force=False, cache_dir=cache_dir)


def update_adapter(
    adapter: Adapter,
    repo_root: Path,
    *,
    force: bool = False,
    cache_dir: Path | None = None,
) -> list[str]:
    """Re-install *adapter* against the existing lock, diffing the inventory.

    Files in the old lock that the new staging no longer produces are
    removed when they still hash to their locked baseline, and preserved
    when locally modified. Locally modified files the new staging *would*
    overwrite abort the update (all of them listed) unless *force*. Returns
    the preserved-drift paths, skills-dir-relative. Raises `AdapterError`.
    """
    lock = read_lock(repo_root)
    if lock is None:
        raise AdapterError(
            f"Adapter '{adapter.name}': no adapter installed in {repo_root} "
            f"({repo_root / SKILLSET_LOCK_PATH} is missing).\n"
            f"  An update replaces a tracked install, and there is nothing "
            f"tracked here.\n"
            f"  How to fix: run 'rcorn skills install' first."
        )
    if lock.adapter != adapter.name:
        raise AdapterError(
            f"Adapter '{adapter.name}': project {repo_root} has adapter "
            f"'{lock.adapter}' installed (per {repo_root / SKILLSET_LOCK_PATH}).\n"
            f"  An update only replaces the adapter the lockfile tracks — "
            f"updating a different one would orphan '{lock.adapter}'s files.\n"
            f"  How to fix: update '{lock.adapter}', or remove it before "
            f"installing '{adapter.name}'."
        )
    return _install_or_update(
        adapter, repo_root, lock=lock, force=force, cache_dir=cache_dir
    )


def _install_or_update(
    adapter: Adapter,
    repo_root: Path,
    *,
    lock: SkillsetLock | None,
    force: bool,
    cache_dir: Path | None,
) -> list[str]:
    """The one install path: fetch, stage, check ownership, commit or roll back."""
    # Pure checks first: a contradictory adapter fails before any fetch or write.
    validate_patch_targets(adapter)
    render_wiring(adapter.wiring)

    skills_root = repo_root / skills_dir(repo_root)
    cache = cache_dir if cache_dir is not None else default_cache_dir()
    # Only a lock pinning this very source can vouch for the archive digest.
    expected_digest = (
        lock.archive_sha256
        if lock is not None
        and lock.repo == adapter.source.repo
        and lock.commit == adapter.source.commit
        else None
    )

    work = Path(tempfile.mkdtemp(prefix="reinicorn-skillset-install-"))
    transaction = _Transaction(work / "backup", adapter.name)
    try:
        tree, digest = fetch_source(
            adapter.source, cache, expected_digest=expected_digest
        )
        # fetch_source hands us ownership of the extracted tree's temp parent.
        try:
            hashes = build_staging(adapter, tree, work / "staging")
        finally:
            shutil.rmtree(tree.parent, ignore_errors=True)

        owned = dict(lock.files) if lock is not None else {}
        _check_collisions(adapter, repo_root, skills_root, hashes, owned)
        _check_local_edits(adapter, skills_root, hashes, owned, force=force)
        removals, preserved = _plan_removals(skills_root, hashes, owned)
        _commit(
            adapter,
            repo_root,
            skills_root,
            staging=work / "staging",
            hashes=hashes,
            removals=removals,
            digest=digest,
            transaction=transaction,
        )
    finally:
        # A failed rollback whose durable relocation itself failed preserves
        # its backups under work/backup and asks us to leave work alone —
        # deleting it here would destroy the only surviving copy of the data.
        if not transaction.preserve_work:
            shutil.rmtree(work, ignore_errors=True)
    return preserved


def _commit(
    adapter: Adapter,
    repo_root: Path,
    skills_root: Path,
    *,
    staging: Path,
    hashes: dict[str, str],
    removals: list[str],
    digest: str,
    transaction: _Transaction,
) -> None:
    """Write skills, removals, wiring doc, lockfile, and link — or roll back."""
    try:
        transaction.backup_root.mkdir(parents=True)
        for rel in sorted(hashes):
            target = skills_root / rel
            transaction.track(target)
            transaction.ensure_parents(target)
            _remove(target)
            shutil.copy2(staging / rel, target)

        for rel in removals:
            target = skills_root / rel
            transaction.track(target)
            _remove(target)
            _prune_empty_dirs(target.parent, skills_root)

        doc = wiring_doc_path(repo_root)
        transaction.track(doc)
        transaction.ensure_parents(doc)
        write_wiring(repo_root, adapter.wiring)

        lock_path = repo_root / SKILLSET_LOCK_PATH
        transaction.track(lock_path)
        transaction.ensure_parents(lock_path)
        write_lock(
            repo_root,
            SkillsetLock(
                adapter=adapter.name,
                repo=adapter.source.repo,
                commit=adapter.source.commit,
                archive_sha256=digest,
                files=dict(hashes),
                wiring=adapter.wiring,
            ),
        )

        link_rel = skills_link(repo_root)
        if link_rel is not None:
            link = repo_root / link_rel
            # Only a REAL (non-symlink) directory is guaranteed left alone by
            # maintain_link — an absent path gets created, and ANY symlink
            # may be relinked if it is stale, so both must be tracked.
            # (Tracking a symlink maintain_link decides not to touch is
            # safe and cheap: the backup just goes unused.) This predicate
            # mirrors `maintain_link`'s mutation cases — if a new one is
            # added there, add it here too, or the link maintain_link
            # writes escapes the transaction and survives a rollback.
            real_dir = link.is_dir() and not link.is_symlink()
            if not real_dir:
                transaction.track(link)
                transaction.ensure_parents(link)
        maintain_link(repo_root)
    except OSError as exc:
        transaction.rollback(cause=exc)
        raise AdapterError(
            f"Adapter '{adapter.name}': failed while writing into {repo_root} "
            f"({exc}).\n"
            f"  Every output was rolled back — the project is unchanged.\n"
            f"  How to fix: check the permissions and free space on "
            f"{repo_root}, then re-run."
        ) from exc
    except BaseException as exc:
        transaction.rollback(cause=exc)
        raise


class _Transaction:
    """Backup ledger making a write set all-or-nothing.

    Every path the commit will create, replace, or remove is tracked (with a
    copy of its previous content, or a note that it was absent) before it is
    touched; `rollback` restores each one and prunes the directories the
    commit created.
    """

    def __init__(self, backup_root: Path, adapter_name: str) -> None:
        self.backup_root = backup_root
        self._adapter_name = adapter_name
        self._backups: dict[Path, Path | None] = {}
        self._created_dirs: list[Path] = []
        # Set when a rollback failure can't even relocate its backups
        # durably: the caller must then leave the work dir (and this
        # transaction's backup_root within it) on disk rather than delete it.
        self.preserve_work = False

    def track(self, target: Path) -> None:
        """Snapshot *target*'s current state, once, before it is written."""
        if target in self._backups:
            return
        if not target.is_symlink() and not target.exists():
            self._backups[target] = None
            return
        backup = self.backup_root / f"{len(self._backups):06d}"
        _copy_path(target, backup)
        self._backups[target] = backup

    def ensure_parents(self, target: Path) -> None:
        """Create *target*'s missing parent directories, recording each one."""
        missing: list[Path] = []
        parent = target.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for directory in reversed(missing):
            directory.mkdir()
            self._created_dirs.append(directory)

    def rollback(self, *, cause: BaseException | None = None) -> None:
        """Restore every tracked path and drop the directories we created.

        Whatever broke the commit (ENOSPC, EACCES) tends to break the restore
        too, so a failing path never aborts the rest: each one is restored
        under its own guard. If any failed, the backups are moved somewhere
        durable — the caller deletes the work dir right after us — and
        `AdapterError` names the paths, their backups, and the manual repair.
        *cause* is the exception that triggered this rollback, if any; a
        rollback-failure error is chained to it via `__cause__`.
        """
        failed: list[tuple[Path, Path | None]] = []
        for target, backup in self._backups.items():
            try:
                _remove(target)
                if backup is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    _copy_path(backup, target)
            except OSError:
                failed.append((target, backup))
        deepest_first = sorted(
            self._created_dirs, key=lambda path: len(path.parts), reverse=True
        )
        for directory in deepest_first:
            with suppress(OSError):  # non-empty: something else lives there now
                directory.rmdir()
        if failed:
            raise self._rollback_failed_error(failed) from cause

    def _rollback_failed_error(
        self, failed: list[tuple[Path, Path | None]]
    ) -> AdapterError:
        """Preserve the backups of the unrestored paths and describe the repair."""
        try:
            durable = Path(tempfile.mkdtemp(prefix="reinicorn-skillset-backup-"))
        except OSError:
            # Can't even make the durable relocation dir (disk full, EACCES —
            # the same condition that likely caused the failure). Don't touch
            # the backups at all: leave them where `track` already put them,
            # under this transaction's own backup_root, and tell the caller
            # (via preserve_work) not to delete that directory.
            self.preserve_work = True
            listing = ""
            for target, backup in failed:
                listing += f"    {target}\n"
                if backup is None:
                    listing += "      backup: none — the path did not exist before\n"
                    continue
                listing += f"      backup: {backup}\n"
            return AdapterError(
                f"Adapter '{self._adapter_name}': the rollback of a failed "
                f"write could not restore {len(failed)} path(s), and its "
                f"backups could not be relocated to a durable location "
                f"either:\n"
                f"{listing}"
                f"  Every other path was rolled back, but those are still "
                f"missing or hold partial install output.\n"
                f"  Their original contents are preserved in "
                f"{self.backup_root} — Reinicorn will not delete it.\n"
                f"  How to fix: copy each backup above back over its path, "
                f"then remove {self.backup_root}."
            )
        listing = ""
        any_relocation_failed = False
        for target, backup in failed:
            listing += f"    {target}\n"
            if backup is None:
                listing += "      backup: none — the path did not exist before\n"
                continue
            kept = durable / backup.name
            try:
                shutil.move(str(backup), str(kept))
            except OSError:
                # Couldn't relocate this one out of the work dir — its only
                # surviving copy is still where `track` put it, under
                # backup_root. Keep the work dir alive (the caller's
                # `finally` would otherwise rmtree it out from under the
                # backup) and point at where it actually lives.
                any_relocation_failed = True
                self.preserve_work = True
                listing += (
                    f"      backup: {backup} (could not relocate to {durable} "
                    f"— preserved in place under {self.backup_root})\n"
                )
                continue
            listing += f"      backup: {kept}\n"
        also_backup_root = (
            f"  Some backups also remain in {self.backup_root} — Reinicorn "
            f"will not delete it either.\n"
            if any_relocation_failed
            else ""
        )
        remove_also = f" and {self.backup_root}" if any_relocation_failed else ""
        return AdapterError(
            f"Adapter '{self._adapter_name}': the rollback of a failed write "
            f"could not restore {len(failed)} path(s):\n"
            f"{listing}"
            f"  Every other path was rolled back, but those are still missing "
            f"or hold partial install output.\n"
            f"  Their original contents are preserved in {durable} — "
            f"Reinicorn will never delete it.\n"
            f"{also_backup_root}"
            f"  How to fix: copy each backup above back over its path, then "
            f"remove {durable}{remove_also}."
        )


def _check_collisions(
    adapter: Adapter,
    repo_root: Path,
    skills_root: Path,
    hashes: dict[str, str],
    owned: dict[str, str],
) -> None:
    """Refuse to write over anything the previous lock does not already own.

    Spec: a declared install path colliding with a native skill or any
    unmanaged existing file is an error, never an overwrite. Both the skill
    directories the adapter claims and the individual staged files are
    checked, so an unmanaged directory of the same name is caught even when
    none of its files happen to share a staged name.

    The reinicorn-generated wiring doc is rejected outright: `_commit`
    rewrites it after the lock has recorded the adapter's own hash for it,
    which would leave the install permanently stuck reporting local edits.
    """
    doc = wiring_doc_path(repo_root)
    doc_rel = (
        doc.relative_to(skills_root).as_posix()
        if doc.is_relative_to(skills_root)
        else None
    )
    if doc_rel is not None and doc_rel in hashes:
        raise AdapterError(
            f"Adapter '{adapter.name}': install path '{doc_rel}' is the wiring "
            f"doc Reinicorn generates itself.\n"
            f"  Reinicorn rewrites that file on every install and update, so "
            f"an adapter-supplied copy would be overwritten immediately and "
            f"then flagged as a local edit forever. Nothing was installed.\n"
            f"  How to fix: remove '{doc_rel}' from the adapter's 'skills' / "
            f"'files' / 'overrides' mapping — the adapter's 'wiring' block "
            f"already controls what that doc says."
        )

    manifest_files = _manifest_files(repo_root)
    for installed_name in sorted(set(adapter.skills.values())):
        directory = skills_root / installed_name
        prefix = f"{installed_name}/"
        if (directory.is_symlink() or directory.exists()) and not any(
            rel == installed_name or rel.startswith(prefix) for rel in owned
        ):
            raise _collision_error(
                adapter, repo_root, directory, installed_name, manifest_files
            )

    for rel in sorted(hashes):
        target = skills_root / rel
        if rel not in owned and (target.is_symlink() or target.exists()):
            raise _collision_error(adapter, repo_root, target, rel, manifest_files)


def _collision_error(
    adapter: Adapter,
    repo_root: Path,
    path: Path,
    rel: str,
    manifest_files: frozenset[str],
) -> AdapterError:
    return AdapterError(
        f"Adapter '{adapter.name}': install path '{rel}' already exists at "
        f"{path}, and it is {_describe_owner(repo_root, path, manifest_files)}.\n"
        f"  Reinicorn only replaces files its own lockfile records, so nothing "
        f"was installed.\n"
        f"  How to fix: rename the colliding entry in the adapter's 'skills' / "
        f"'files' / 'overrides' mapping, or move {path} aside if it is no "
        f"longer needed."
    )


def _describe_owner(
    repo_root: Path, path: Path, manifest_files: frozenset[str]
) -> str:
    """Attribute an existing path to a native skill or to nobody."""
    try:
        rel = str(path.relative_to(repo_root))
    except ValueError:  # configured skills dir outside the repo
        rel = str(path)
    if rel in manifest_files:
        return "a native Reinicorn skill file (tracked in the manifest)"
    if any(entry.startswith(f"{rel}/") for entry in manifest_files):
        return "a native Reinicorn skill directory (tracked in the manifest)"
    return "an unmanaged path Reinicorn does not track"


def _manifest_files(repo_root: Path) -> frozenset[str]:
    """Repo-relative paths the Reinicorn manifest claims as native assets."""
    manifest = read_manifest(repo_root)
    if manifest is None:
        return frozenset()
    files = manifest.get("files")
    if not isinstance(files, dict):
        return frozenset()
    return frozenset(str(key) for key in files)


def _check_local_edits(
    adapter: Adapter,
    skills_root: Path,
    hashes: dict[str, str],
    owned: dict[str, str],
    *,
    force: bool,
) -> None:
    """Abort when the new staging would overwrite hand-edited installed files."""
    if force:
        return
    modified = [
        rel
        for rel in sorted(hashes)
        if rel in owned and _is_locally_modified(skills_root / rel, owned[rel])
    ]
    if not modified:
        return
    listing = "".join(f"    {rel}\n" for rel in modified)
    raise AdapterError(
        f"Adapter '{adapter.name}': {len(modified)} installed file(s) under "
        f"{skills_root} have local edits this install would overwrite:\n"
        f"{listing}"
        f"  Nothing was installed.\n"
        f"  How to fix: fold those edits into the adapter (patch/append/"
        f"override) and re-run, or run 'rcorn skills update --force' to "
        f"discard them."
    )


def _is_locally_modified(path: Path, locked_hash: str) -> bool:
    """True if *path* diverges from the lock's record of an owned file.

    A regular file is compared by hash, as before. An owned path replaced
    locally by anything else — a directory, or a symlink (including a
    dangling one, which `.is_file()` also reports False for) — counts as
    modified too: overwriting it without going through the force gate would
    silently destroy a directory (`_remove` rmtree's it) or drop a symlink
    the caller placed there, neither of which is what "local edit" was ever
    meant to skip past.
    """
    if path.is_symlink():
        return True
    if not path.exists():
        return False  # already gone by hand — nothing here to protect
    if not path.is_file():
        return True  # e.g. replaced by a directory
    return sha256_file(path) != locked_hash


def _plan_removals(
    skills_root: Path, hashes: dict[str, str], owned: dict[str, str]
) -> tuple[list[str], list[str]]:
    """Split lock-inventory files the new staging drops into (remove, preserve).

    Spec: dropped files go when they still match their locked hash, and stay
    when locally modified — preserved drift is reported to the caller.
    """
    removals: list[str] = []
    preserved: list[str] = []
    for rel in sorted(owned):
        if rel in hashes:
            continue
        target = skills_root / rel
        if not target.is_file():
            continue  # already gone by hand — nothing to remove or preserve
        if sha256_file(target) == owned[rel]:
            removals.append(rel)
        else:
            preserved.append(rel)
    return removals, preserved


def _copy_path(source: Path, dest: Path) -> None:
    """Copy a file, symlink, or directory verbatim to *dest*."""
    if source.is_symlink():
        dest.symlink_to(source.readlink())
    elif source.is_dir():
        shutil.copytree(source, dest, symlinks=True)
    else:
        shutil.copy2(source, dest)


def _remove(path: Path) -> None:
    """Delete a file, symlink, or directory if it is there."""
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _prune_empty_dirs(start: Path, stop: Path) -> None:
    """Remove *start* and its now-empty ancestors, never reaching *stop*."""
    current = start
    while current != stop and stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            return  # not empty (or gone) — stop climbing
        current = current.parent
