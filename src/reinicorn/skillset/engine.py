"""Patch engine: exclude/patch/append/override/files, canonical order, into staging."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from reinicorn.git import explain_failure, run_git
from reinicorn.manifest import sha256_file
from reinicorn.skillset.adapter import AdapterError

if TYPE_CHECKING:
    from reinicorn.skillset.adapter import Adapter

_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+) b/(.+)$", re.MULTILINE)


def patch_touched_paths(patch_text: str) -> set[str]:
    """Upstream-relative paths a unified diff touches (from 'diff --git a/X b/X').

    Parses only the `diff --git a/X b/X` header lines. Renamed paths and
    quoted (unusual-character) paths are out of scope for skill markdown
    patches.
    """
    paths: set[str] = set()
    for match in _DIFF_GIT_RE.finditer(patch_text):
        paths.add(match.group(1))
        paths.add(match.group(2))
    return paths


def _installed_path_for(adapter: Adapter, upstream_path: str) -> str | None:
    """Translate an upstream-relative path to its installed-relative path.

    Returns `None` if `upstream_path` is not under any of the adapter's
    `skills` directories.
    """
    upstream = Path(upstream_path)
    for upstream_dir, installed_name in adapter.skills.items():
        try:
            rel = upstream.relative_to(upstream_dir)
        except ValueError:
            continue
        return installed_name if str(rel) == "." else f"{installed_name}/{rel.as_posix()}"
    return None


def validate_patch_targets(adapter: Adapter) -> None:
    """AdapterError if any patch touches an excluded file or a file whose
    installed location is overridden (canonical-order contradiction).
    """
    excludes = set(adapter.excludes)
    for rel_patch in adapter.patches:
        patch_text = (adapter.root / rel_patch).read_text()
        for upstream_path in patch_touched_paths(patch_text):
            if upstream_path in excludes:
                raise AdapterError(
                    f"Adapter '{adapter.name}': patch {rel_patch} touches "
                    f"'{upstream_path}', which is also excluded.\n"
                    f"  How to fix: canonical order is exclude -> patch -> "
                    f"append -> override, so a patch can never touch an "
                    f"excluded file — drop '{upstream_path}' from excludes, "
                    f"or remove that hunk from {rel_patch}."
                )
            installed_path = _installed_path_for(adapter, upstream_path)
            if installed_path is not None and installed_path in adapter.overrides:
                raise AdapterError(
                    f"Adapter '{adapter.name}': patch {rel_patch} touches "
                    f"'{upstream_path}' (installed as '{installed_path}'), "
                    f"which is also overridden.\n"
                    f"  How to fix: canonical order applies override after "
                    f"patch, so patching a file that is wholesale replaced is "
                    f"a contradiction — drop '{installed_path}' from "
                    f"overrides, or remove that hunk from {rel_patch}."
                )


def build_staging(adapter: Adapter, source_tree: Path, staging: Path) -> dict[str, str]:
    """Apply exclude -> patch -> append -> override -> files into `staging`
    (installed layout). Returns {installed rel path: sha256}.
    """
    validate_patch_targets(adapter)

    worktree = Path(tempfile.mkdtemp(prefix="reinicorn-skillset-worktree-"))
    try:
        shutil.copytree(source_tree, worktree, dirs_exist_ok=True)
        _apply_excludes(adapter, worktree)
        _apply_patches(adapter, worktree)
        _stage_skills(adapter, worktree, staging)
    finally:
        shutil.rmtree(worktree, ignore_errors=True)

    _apply_appends(adapter, staging)
    _apply_overrides(adapter, staging)
    _apply_files(adapter, staging)

    return _hash_tree(staging)


def _apply_excludes(adapter: Adapter, worktree: Path) -> None:
    """Delete each `excludes` entry from the worktree copy of the source tree."""
    for rel in adapter.excludes:
        target = worktree / rel
        if not target.is_file():
            raise AdapterError(
                f"Adapter '{adapter.name}': excludes entry '{rel}' does not "
                f"exist in {adapter.source.repo}@{adapter.source.commit[:12]}.\n"
                f"  How to fix: fix the path in adapter.yaml, or drop it from "
                f"excludes if it no longer exists upstream."
            )
        target.unlink()


def _apply_patches(adapter: Adapter, worktree: Path) -> None:
    """Apply each `patches` entry, in listed order, against the worktree.

    Runs `git apply` via `reinicorn.git.run_git` (the one seam allowed to
    read a git subprocess's stderr — see tests/test_git_error_surface.py)
    rather than a bare `subprocess.run`, so the failure is reported through
    `explain_failure` like every other git invocation in this codebase.
    """
    for rel_patch in adapter.patches:
        patch_path = str((adapter.root / rel_patch).resolve())
        proc = run_git(
            "apply", "--whitespace=nowarn", patch_path,
            cwd=worktree, check=False,
        )
        if proc.returncode != 0:
            raise AdapterError(
                f"Adapter '{adapter.name}': "
                + "\n".join(explain_failure(
                    f"apply patch {rel_patch} to "
                    f"{adapter.source.repo}@{adapter.source.commit[:12]}",
                    proc,
                    detail=[
                        "How to fix: run the authoring-skillset-adapters "
                        "skill to rebase this adapter.",
                    ],
                ))
            )


def _stage_skills(adapter: Adapter, worktree: Path, staging: Path) -> None:
    """Copy each `skills` upstream directory into `staging/<installed name>`."""
    staging.mkdir(parents=True, exist_ok=True)
    for upstream_dir, installed_name in adapter.skills.items():
        source = worktree / upstream_dir
        if not source.is_dir():
            raise AdapterError(
                f"Adapter '{adapter.name}': skills entry '{upstream_dir}' does "
                f"not exist in {adapter.source.repo}@{adapter.source.commit[:12]}.\n"
                f"  How to fix: fix the upstream path in adapter.yaml's "
                f"'skills' mapping."
            )
        shutil.copytree(source, staging / installed_name)


def _apply_appends(adapter: Adapter, staging: Path) -> None:
    """Append each `appends` block, in listed order, to `<installed name>/SKILL.md`."""
    for installed_name, blocks in adapter.appends.items():
        target = staging / installed_name / "SKILL.md"
        if not target.is_file():
            raise AdapterError(
                f"Adapter '{adapter.name}': appends.{installed_name} targets "
                f"'{installed_name}/SKILL.md', which was not staged.\n"
                f"  How to fix: check that '{installed_name}' is one of the "
                f"'skills' mapping's installed names."
            )
        existing = target.read_text()
        for rel_block in blocks:
            block = (adapter.root / rel_block).read_text()
            existing = existing.rstrip() + "\n\n" + block.rstrip() + "\n"
        target.write_text(existing)


def _apply_overrides(adapter: Adapter, staging: Path) -> None:
    """Replace each `overrides` installed-relative path wholesale."""
    for installed_path, rel in adapter.overrides.items():
        dest = staging / installed_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(adapter.root / rel, dest)


def _apply_files(adapter: Adapter, staging: Path) -> None:
    """Copy each `files` entry to its installed-relative destination as-is."""
    for installed_path, rel in adapter.files.items():
        dest = staging / installed_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(adapter.root / rel, dest)


def _hash_tree(root: Path) -> dict[str, str]:
    """sha256 every file under `root`, keyed by its root-relative posix path."""
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
