"""rcorn update — sync repo assets with installed package version."""

from __future__ import annotations

import shutil
from pathlib import Path

from reinicorn import __version__, console
from reinicorn.assets import get_asset_path
from reinicorn.git import run_git
from reinicorn.manifest import (
    read_manifest,
    sha256_file,
    write_manifest,
    write_manifest_data,
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

    # --diff mode
    if diff_target is not None:
        return _show_diff(repo_root, diff_target)

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

    package_files = _collect_package_files(asset_root)

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


def _collect_package_files(asset_root: Path) -> dict[str, Path]:
    """Collect all files from the package asset directories.

    Handles both wheel layout (skills/, hooks/) and editable layout
    (.agents/skills/, .claude/hooks/) by checking which actually exists.
    """
    files: dict[str, Path] = {}

    # Each entry: (candidate source names, destination prefix)
    asset_probes: list[tuple[list[str], str]] = [
        (["skills", ".agents/skills", ".claude/skills"], ".agents/skills"),
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

    package_files = _collect_package_files(asset_root)

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
