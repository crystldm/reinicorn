"""rcorn skills — skill-set adapter management (install, status, update, list)."""

from __future__ import annotations

from dataclasses import replace

from reinicorn import console
from reinicorn.assets import get_asset_path
from reinicorn.config import skills_dir
from reinicorn.git import repo_root
from reinicorn.manifest import sha256_file
from reinicorn.skillset.adapter import COMMIT_RE, AdapterError, load_adapter
from reinicorn.skillset.installer import install_adapter, update_adapter
from reinicorn.skillset.lockfile import SKILLSET_LOCK_PATH, read_lock
from reinicorn.skillset.restore import (
    locked_adapter,
    resolve_adapter_dir,
    restore_from_lock,
)
from reinicorn.skillset.wiring import wiring_doc_path


def _bundled_adapter_names() -> list[str]:
    adapters_dir = get_asset_path("adapters")
    if adapters_dir is None:
        return []
    return sorted(p.name for p in adapters_dir.iterdir() if p.is_dir())


def cmd_skills_install(name_or_path: str | None) -> int:
    """Install a bundled or local-path skill-set adapter into this repo.

    With no adapter named, restore the one the committed lockfile records —
    the fresh-clone and new-worktree case, where the lock is in git and the
    (possibly gitignored) skill files are not.
    """
    if name_or_path is None:
        return _install_from_lock()

    adapter_dir = resolve_adapter_dir(name_or_path)
    if adapter_dir is None:
        names = _bundled_adapter_names()
        listing = ", ".join(names) if names else "(none bundled)"
        console.error(
            f"Skill-set adapter '{name_or_path}' is not a directory and not a "
            f"bundled adapter name.\n"
            f"  Bundled adapters: {listing}\n"
            f"  How to fix: pass a path to an adapter directory, or one of the "
            f"bundled names above."
        )
        return 1

    root = repo_root()
    if root is None:
        return 1

    try:
        adapter = load_adapter(adapter_dir)
        preserved = install_adapter(adapter, root)
    except AdapterError as e:
        console.error(str(e))
        return 1

    lock = read_lock(root)
    file_count = len(lock.files) if lock is not None else 0
    doc = wiring_doc_path(root)
    console.success(
        f"Installed '{adapter.name}' @ {adapter.source.commit[:12]} "
        f"({file_count} file(s))."
    )
    console.info(f"Wiring doc: {doc}")
    if preserved:
        console.warn(
            f"{len(preserved)} locally modified file(s) preserved (not touched):"
        )
        for rel in preserved:
            console.info(f"  {rel}")
    return 0


def _install_from_lock() -> int:
    """`rcorn skills install` with no argument: bring back what the lock records."""
    root = repo_root()
    if root is None:
        return 1

    lock = read_lock(root)
    if lock is None:
        names = _bundled_adapter_names()
        listing = ", ".join(names) if names else "(none bundled)"
        console.error(
            f"No adapter named, and no lockfile to restore from "
            f"({root / SKILLSET_LOCK_PATH} is missing).\n"
            f"  Without an argument, install restores the adapter a committed "
            f"lockfile records; this project has none.\n"
            f"  How to fix: name the adapter to install — a bundled name "
            f"({listing}) or a path to an adapter directory."
        )
        return 1

    try:
        restored = restore_from_lock(root, lock)
    except AdapterError as e:
        console.error(str(e))
        return 1

    if restored:
        console.success(
            f"Restored {len(restored)} file(s) of '{lock.adapter}' @ "
            f"{lock.commit[:12]}."
        )
    else:
        console.success(
            f"'{lock.adapter}' @ {lock.commit[:12]} is complete — nothing to restore."
        )
    console.info(f"Wiring doc: {wiring_doc_path(root)}")
    return 0


def cmd_skills_status() -> int:
    """Report the installed adapter's pin and any local drift from its lock."""
    root = repo_root()
    if root is None:
        return 1

    lock = read_lock(root)
    if lock is None:
        console.info("no adapter installed")
        return 0

    header = f"{lock.adapter}: {lock.repo}@{lock.commit[:12]}"
    annotation = _lookup_annotation(lock.adapter, lock.commit)
    if annotation:
        header += f" ({annotation})"
    console.info(header)

    skills_root = root / skills_dir(root)
    drift = False
    for rel in sorted(lock.files):
        target = skills_root / rel
        if not target.is_file():
            console.info(f"missing: {rel}")
            drift = True
        elif sha256_file(target) != lock.files[rel]:
            console.info(f"modified: {rel}")
            drift = True
    if not drift:
        console.info("no local drift")
    return 0


def _lookup_annotation(adapter_name: str, commit: str) -> str | None:
    """Best-effort annotation lookup by re-resolving the adapter's own bundle.

    Only a bundled adapter (or one still present at a cwd-relative directory
    of the same name) can be re-resolved; a lockfile carries no annotation
    of its own, so an unresolvable or drifted-pin adapter simply omits it.
    """
    adapter_dir = resolve_adapter_dir(adapter_name)
    if adapter_dir is None:
        return None
    try:
        adapter = load_adapter(adapter_dir)
    except AdapterError:
        return None
    if adapter.source.commit != commit:
        return None
    return adapter.source.annotation


def cmd_skills_update(ref: str | None = None, force: bool = False) -> int:
    """Re-fetch and re-apply the installed adapter, optionally moving the pin."""
    if ref is not None and not COMMIT_RE.match(ref):
        console.error(
            f"--ref '{ref}' is not a 40-hex commit SHA.\n"
            f"  Tags are not valid pins — resolve the tag to its commit and "
            f"pass that full SHA."
        )
        return 1

    root = repo_root()
    if root is None:
        return 1

    lock = read_lock(root)
    if lock is None:
        console.error(
            "No adapter installed — nothing to update.\n"
            "  How to fix: run 'rcorn skills install <adapter>' first."
        )
        return 1

    try:
        # Without --ref, `locked_adapter` re-applies the lock's pinned commit
        # (clearing the annotation when the adapter's own pin has moved on).
        adapter = locked_adapter(lock)
        if ref is not None:
            adapter = replace(
                adapter,
                source=replace(
                    adapter.source, commit=ref, annotation=f"cli --ref {ref}"
                ),
            )
        preserved = update_adapter(adapter, root, force=force)
    except AdapterError as e:
        console.error(str(e))
        return 1

    console.success(f"Updated '{adapter.name}' @ {adapter.source.commit[:12]}.")
    if preserved:
        console.warn(
            f"{len(preserved)} locally modified file(s) preserved (not touched):"
        )
        for rel in preserved:
            console.info(f"  {rel}")
    return 0


def cmd_skills_list() -> int:
    """List bundled skill-set adapters (name, source repo, annotation)."""
    adapters_dir = get_asset_path("adapters")
    if adapters_dir is None:
        console.info("no bundled adapters")
        return 0

    names = sorted(p.name for p in adapters_dir.iterdir() if p.is_dir())
    if not names:
        console.info("no bundled adapters")
        return 0

    for name in names:
        try:
            adapter = load_adapter(adapters_dir / name)
        except AdapterError as e:
            console.warn(f"{name}: {e}")
            continue
        console.info(
            f"{name}: {adapter.source.repo} ({adapter.source.annotation})"
        )
    return 0
