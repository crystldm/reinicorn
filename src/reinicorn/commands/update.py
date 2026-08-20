"""rcorn update — sync repo assets with installed package version."""

from __future__ import annotations

import shutil
from pathlib import Path

from reinicorn import __version__, console
from reinicorn.assets import get_asset_path
from reinicorn.commands.hooks_install import cmd_hooks_install
from reinicorn.config import config_get, config_set, skills_dir
from reinicorn.git import run_git
from reinicorn.identity import SKILLSET_MIGRATION_KEY
from reinicorn.manifest import (
    read_manifest,
    sha256_file,
    write_manifest,
    write_manifest_data,
)
from reinicorn.skillset.adapter import Adapter, AdapterError, load_adapter
from reinicorn.skillset.installer import install_adapter
from reinicorn.skillset.lockfile import read_lock
from reinicorn.skillset.wiring import wiring_doc_path, write_wiring

_SUPERPOWERS_ADAPTER = "superpowers"

# Skills-dir top-level names a pre-adapter Reinicorn shipped that the
# superpowers adapter does not declare: the fork-updating helper skill and
# the shared attribution file. Together with the adapter's own installed
# skill names these are the complete legacy inventory.
_LEGACY_EXTRA_NAMES = frozenset({"update-superpowers", "ATTRIBUTION.md"})

_MIGRATION_PROMPT = (
    "Legacy superpowers skill forks detected (shipped by an older Reinicorn).\n"
    "These are now provided by the 'superpowers' skill-set adapter instead.\n"
    "Migrate now? Installs the adapter (network required) and removes the old\n"
    "copies; locally modified files are kept. Answer 'n' to keep the old forks\n"
    "and never ask again (rcorn skills install superpowers migrates later)."
)


def _get_package_version() -> str:
    return __version__


def _get_repo_root() -> Path:
    from reinicorn.git import repo_root
    root = repo_root(quiet=True)
    if root is None:
        # Fallback to raw git (shouldn't happen if CLI entry checked)
        r = run_git("rev-parse", "--show-toplevel", check=False)
        return Path(r.stdout.strip())
    return root


def _get_asset_sources() -> Path | None:
    """Return the root directory containing package assets.

    Assets may be under <root>/skills/ (wheel) or <root>/.agents/skills/
    (editable install). We probe for known asset names and strip one parent
    per probe component to recover the true asset root.

    Returning found.parent unconditionally broke editable installs: a
    ".agents/skills" hit yielded ".agents/", hiding the sibling hooks/,
    linters/, and AGENTS.md at the repo root and silently dropping them from
    'rcorn update'.
    """
    for probe in ("skills", ".agents/skills", ".claude/skills"):
        found = get_asset_path(probe)
        if found is not None and found.is_dir() and found.name == "skills":
            root = found
            for _ in Path(probe).parts:
                root = root.parent
            return root
    return None


def _native_skill_names(asset_root: Path) -> set[str]:
    """Top-level directory names of the currently bundled native skills.

    Mirrors the probe order `_collect_package_files` uses to find the
    skills asset dir, so 'native' always means 'still shipped by this
    package' — never a second, hand-maintained list to fall out of sync.
    """
    for candidate in ("skills", ".agents/skills", ".claude/skills"):
        src = asset_root / candidate
        if src.is_dir():
            return {p.name for p in src.iterdir() if p.is_dir()}
    return set()


def _legacy_fork_names(adapter: Adapter, native_skills: set[str]) -> set[str]:
    """Skills-dir top-level names a pre-adapter Reinicorn shipped.

    An explicit inventory — the adapter's own installed skill names plus the
    extras that never had an adapter counterpart — never "anything the
    package no longer ships". The manifest tracks the whole skills
    directory, so the latter would classify a user-authored skill as a
    legacy fork and let the cleanup below delete it.

    Currently-shipped native names are subtracted so a name the package
    still owns is synced by update, never migrated out from under it.
    """
    return (set(adapter.skills.values()) | _LEGACY_EXTRA_NAMES) - native_skills


def _legacy_fork_files(
    repo_root: Path, manifest_files: dict, legacy_names: set[str]
) -> dict[str, dict]:
    """Manifest entries under the skills dir named by the legacy inventory.

    These are the vendored superpowers forks a pre-adapter Reinicorn shipped:
    still tracked in the manifest, no longer part of the package.
    """
    prefix = f"{skills_dir(repo_root).as_posix()}/"
    return {
        rel: meta
        for rel, meta in manifest_files.items()
        if rel.startswith(prefix)
        and rel[len(prefix):].split("/", 1)[0] in legacy_names
    }


def _prune_empty_dirs(start: Path, stop: Path) -> None:
    """Remove *start* and its now-empty ancestors, never reaching *stop*."""
    current = start
    while current != stop and stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            return  # not empty (or gone) — stop climbing
        current = current.parent


def _maybe_migrate_legacy_forks(
    repo_root: Path, manifest: dict, manifest_files: dict
) -> None:
    """Detect legacy superpowers forks and offer the one-time adapter migration.

    Spec: `rcorn update` on a legacy project detects the old vendored forks
    via the asset manifest and offers to replace them with the bundled
    'superpowers' skill-set adapter — behavior-preserving by default,
    explicit opt-out to go adapter-less; locally modified forks are flagged
    and never silently deleted.
    """
    if read_lock(repo_root) is not None:
        return  # already migrated (a lock means an adapter is installed)
    if config_get(SKILLSET_MIGRATION_KEY, root=repo_root) == "declined":
        return  # durable opt-out from a previous run

    asset_root = _get_asset_sources()
    if asset_root is None:
        return  # can't tell what's native here; the rest of update reports this

    # The adapter is loaded before detection, not after the prompt: it
    # declares which skill names the legacy forks used, and that inventory
    # is what makes detection safe for hand-written skills.
    adapter_dir = get_asset_path(f"adapters/{_SUPERPOWERS_ADAPTER}")
    if adapter_dir is None:
        return  # no adapter to migrate to, and no inventory to classify with

    try:
        adapter = load_adapter(adapter_dir)
    except AdapterError as exc:
        console.error(
            f"Cannot read the bundled '{_SUPERPOWERS_ADAPTER}' adapter: {exc}\n"
            f"  Is reinicorn installed correctly? Try: uv pip install -e ."
        )
        return

    legacy = _legacy_fork_files(
        repo_root,
        manifest_files,
        _legacy_fork_names(adapter, _native_skill_names(asset_root)),
    )
    if not legacy:
        return

    if not console.is_interactive():
        # Nobody is there to answer. Skipping outright — rather than taking
        # silence for a "no" — keeps the durable opt-out something the user
        # actually chose, and leaves a later interactive run free to ask.
        return

    if not console.confirm(_MIGRATION_PROMPT):
        config_set(SKILLSET_MIGRATION_KEY, "declined", repo_root)
        return

    # The legacy forks are still on disk when the installer runs, so the
    # transaction must adopt them (replace hash-clean copies, preserve
    # drifted ones) instead of flagging them as unmanaged collisions.
    prefix = f"{skills_dir(repo_root).as_posix()}/"
    adopt_hashes = {
        rel[len(prefix):]: meta["sha256"] for rel, meta in legacy.items()
    }

    try:
        install_adapter(adapter, repo_root, adopt_hashes=adopt_hashes)
    except AdapterError as exc:
        console.error(str(exc))
        console.warn(
            "Legacy fork migration failed — the old copies were left in place.\n"
            "  Nothing was recorded, so 'rcorn update' will offer to migrate "
            "again next time."
        )
        return

    # The transaction just handled every legacy file the adapter also
    # produces (hash-clean → replaced, drifted → preserved with a warning).
    # Only legacy files with no adapter counterpart are left to clean up:
    # hash-clean → delete, drifted → preserve and warn.
    lock = read_lock(repo_root)
    produced = set(lock.files) if lock is not None else set()
    skl_root = repo_root / skills_dir(repo_root)
    for rel, meta in legacy.items():
        if rel[len(prefix):] in produced:
            continue
        target = repo_root / rel
        if target.is_file() and sha256_file(target) == meta["sha256"]:
            target.unlink()
            _prune_empty_dirs(target.parent, skl_root)
        else:
            console.warn(f"{rel} is locally modified — kept (not migrated).")

    # Drop the migrated entries so the "Removed upstream" warning loop
    # further down doesn't re-flag them (manifest_files is the same dict as
    # manifest["files"], so this mutation is visible to that loop too).
    for rel in legacy:
        manifest_files.pop(rel, None)
    write_manifest_data(repo_root, manifest)
    console.success(
        f"Migrated legacy superpowers forks to the '{_SUPERPOWERS_ADAPTER}' adapter."
    )


def _regenerate_wiring_doc(repo_root: Path) -> None:
    """Regenerate the skillset wiring doc so it always exists after update.

    Rendered from the lock's wiring when an adapter is installed,
    registry-only otherwise — binding rule: `using-reinicorn`'s pointer to
    this doc must never dangle. A write failure (e.g. an unwritable skills
    dir) must not crash `rcorn update`; warn and move on, the doc will
    regenerate on the next successful run.
    """
    try:
        lock = read_lock(repo_root)
        write_wiring(repo_root, lock.wiring if lock is not None else None)
    except Exception as exc:
        console.warn(
            f"Could not regenerate the skillset wiring doc: {exc}\n"
            f"  Where: {wiring_doc_path(repo_root)}\n"
            f"  How to fix: check write permissions under "
            f"{skills_dir(repo_root)}, then rerun 'rcorn update'."
        )


def cmd_update(*, diff_target: str | None = None) -> int:
    """Sync repo assets with installed package version."""
    pkg_version = _get_package_version()
    repo_root = _get_repo_root()

    manifest = read_manifest(repo_root)

    if manifest is None:
        console.error(
            "No valid .reinicorn/manifest.json found.\n"
            "  Run 'rcorn init' first to set up this repo."
        )
        return 1

    manifest_files = manifest["files"]
    legacy_agents_owned = "AGENTS.md" in manifest_files
    manifest_files.pop("AGENTS.md", None)

    # --diff mode: read-only, so it must return before the migration below
    # can tear anything down.
    if diff_target is not None:
        return _show_diff(repo_root, diff_target)

    from reinicorn.kb_migrate import detect_submodule_layout, migrate_submodule_to_clone
    if detect_submodule_layout(repo_root):
        console.info("Detected the old kb submodule layout.")
        if not migrate_submodule_to_clone(repo_root):
            return 1
        # The init path installs hooks as part of its own asset-setup flow;
        # update has no such flow, so a migrated repo would otherwise be
        # left without spec §10's pre-commit hook until the next full init.
        if cmd_hooks_install() != 0:
            console.warn("Hook installation had issues — review output above.")

    # Placed before the version-equality early return below: a same-version
    # repo must still get the one-time migration offer (spec: detection is
    # keyed on the manifest and lockfile, not on whether there's anything
    # else to sync).
    _maybe_migrate_legacy_forks(repo_root, manifest, manifest_files)

    # Runs unconditionally, before the version-equality branch below, so
    # both exit paths — "Already up to date" and a full sync — regenerate
    # the doc. It must reflect any lock change the migration above just
    # made, hence placed after it rather than once at the top of the
    # function.
    _regenerate_wiring_doc(repo_root)

    manifest_version = manifest["reinicorn_version"]
    if manifest_version == pkg_version:
        if legacy_agents_owned:
            write_manifest_data(repo_root, manifest)
        console.success(f"Already up to date (v{pkg_version}).")
        return 0

    print()
    console.header("Reinicorn Update")
    print("================")
    print()
    console.info(f"v{manifest_version} → v{pkg_version}")
    print()

    asset_root = _get_asset_sources()
    if asset_root is None:
        console.error(
            "Cannot locate package assets.\n"
            "  Searched for: skills/, .agents/skills/, .claude/skills/\n"
            "  Is reinicorn installed correctly? Try: uv pip install -e ."
        )
        return 1

    counts = {"updated": 0, "added": 0, "skipped": 0}

    package_files = _collect_package_files(asset_root, repo_root)

    # Adapter-installed files (recorded in the skillset lock) are owned by
    # `rcorn skills`, not `rcorn update` — never sync, warn, or count them.
    lock = read_lock(repo_root)
    if lock is not None:
        skl_dir = skills_dir(repo_root)
        lock_owned = {(skl_dir / rel).as_posix() for rel in lock.files}
        package_files = {
            rel: src for rel, src in package_files.items() if rel not in lock_owned
        }

    for rel_path, src_path in sorted(package_files.items()):
        dest = repo_root / rel_path

        if rel_path in manifest_files:
            if dest.is_file():
                current_hash = sha256_file(dest)
                manifest_hash = manifest_files[rel_path]["sha256"]
                if current_hash == manifest_hash:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, dest)
                    counts["updated"] += 1
                else:
                    console.warn(f"Skipped {rel_path} (locally modified)")
                    print(f"    Run: rcorn update --diff {rel_path}")
                    counts["skipped"] += 1
            else:
                answer = input(
                    f"  {rel_path} was deleted. Re-add? [y/N] "
                ).strip().lower()
                if answer == "y":
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, dest)
                    counts["added"] += 1
                else:
                    counts["skipped"] += 1
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest)
            counts["added"] += 1

    # Warn about files removed upstream
    for rel_path in manifest_files:
        if rel_path not in package_files and (repo_root / rel_path).is_file():
            console.warn(f"Removed upstream: {rel_path}")

    print()
    print(f"  rcorn update: v{manifest_version} → v{pkg_version}")
    print(f"    Updated: {counts['updated']} files")
    print(f"    Added:   {counts['added']} files")
    print(f"    Skipped: {counts['skipped']} files (locally modified)")
    print()

    write_manifest(repo_root, version=pkg_version)

    # Phase 2: upgrade notes
    _show_upgrade_notes(asset_root, manifest_version, pkg_version)

    return 0


def _collect_package_files(asset_root: Path, repo_root: Path) -> dict[str, Path]:
    """Collect all files from the package asset directories.

    Handles both wheel layout (skills/, hooks/) and editable layout
    (.agents/skills/, .claude/hooks/) by checking which actually exists.

    Only the *source* layout is probed: the native-skill destination is
    whatever `REINICORN_SKILLS_DIR` configures for *repo_root*, so update
    writes to the same tree init and the manifest use.
    """
    files: dict[str, Path] = {}

    # Each entry: (candidate source names, destination prefix)
    asset_probes: list[tuple[list[str], str]] = [
        (
            ["skills", ".agents/skills", ".claude/skills"],
            skills_dir(repo_root).as_posix(),
        ),
        (["hooks", ".claude/hooks"], ".claude/hooks"),
        (["editor-hooks"], ".reinicorn/hooks"),
        (["linters"], "linters"),
    ]

    for candidates, dest_prefix in asset_probes:
        for candidate in candidates:
            src = asset_root / candidate
            if src.is_dir():
                for f in sorted(src.rglob("*")):
                    if f.is_file():
                        rel = f.relative_to(src)
                        files[f"{dest_prefix}/{rel}"] = f
                break  # Use first match, don't double-count

    return files


def _show_diff(repo_root: Path, target: str) -> int:
    """Show diff between repo file and upstream version."""
    import difflib

    asset_root = _get_asset_sources()
    if asset_root is None:
        console.error(
            "Cannot locate package assets.\n"
            "  Is reinicorn installed correctly? Try: uv pip install -e ."
        )
        return 1

    package_files = _collect_package_files(asset_root, repo_root)

    matches = [k for k in package_files if target in k]
    if not matches:
        console.error(
            f"No asset matching '{target}' found.\n"
            f"  Available assets: {', '.join(sorted(package_files.keys())[:10])}"
        )
        return 1

    for rel_path in matches:
        repo_file = repo_root / rel_path
        pkg_file = package_files[rel_path]

        if not repo_file.is_file():
            console.warn(f"{rel_path}: not present in repo")
            continue

        repo_lines = repo_file.read_text().splitlines(keepends=True)
        pkg_lines = pkg_file.read_text().splitlines(keepends=True)

        diff = difflib.unified_diff(
            repo_lines, pkg_lines,
            fromfile=f"repo/{rel_path}",
            tofile=f"upstream/{rel_path}",
        )
        diff_text = "".join(diff)
        if diff_text:
            print(diff_text)
        else:
            console.info(f"{rel_path}: no differences")

    return 0


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse dotted version string into comparable tuple."""
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def _show_upgrade_notes(
    asset_root: Path, from_version: str, to_version: str
) -> None:
    """Display upgrade notes for versions between from and to."""
    upgrades_dir = asset_root / "upgrades"
    if not upgrades_dir.is_dir():
        return

    notes_files = sorted(upgrades_dir.glob("v*.md"))
    if not notes_files:
        return

    from_parsed = _parse_version(from_version)
    to_parsed = _parse_version(to_version)

    shown = False
    for notes_file in notes_files:
        file_version = notes_file.stem.lstrip("v")
        file_parsed = _parse_version(file_version)
        if from_parsed < file_parsed <= to_parsed:
            if not shown:
                console.header("Upgrade Notes")
                print("=============")
                print()
                shown = True
            print(notes_file.read_text())
            print()
