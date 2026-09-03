"""The `closes` behavior's shared logic: stages, closer paths, overlap.

A closable type's docs live in a stage dir (``{stage}/{branch}/<name>``);
its closer's doc rides in the same dir. This module owns the stage
vocabulary and every computation both the lifecycle commands and the lints
need, so the two can never disagree about where a branch's docs live
(spec: process-as-config §2c).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from reinicorn import console, frontmatter
from reinicorn.corpus import doc_path
from reinicorn.doc_types import DocType, closable_types, registry
from reinicorn.git import repo_root
from reinicorn.kb import branch_changed_files, branch_dir_name, get_kb_dir

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

STAGE_ACTIVE = "active"
STAGE_COMPLETED = "completed"
STAGES = (STAGE_ACTIVE, STAGE_COMPLETED)

_EMPTY_BULLET_LINE = re.compile(r"^\s*-\s*(\[ \]\s*)?(_[^_]*_)?\s*$")


def sections_empty(text: str) -> bool:
    """True when a doc's body has no filled-in bullet content.

    Reads the body only: frontmatter keys are metadata, and counting them
    as content would make every doc look filled in.
    """
    for line in frontmatter.parse(text)[1].splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("**"):
            continue
        if _EMPTY_BULLET_LINE.match(line):
            continue
        return False
    return True


def branch_dir(repo_dir: Path, dt: DocType, branch: str, stage: str) -> Path:
    """The stage dir a branch's docs of closable type *dt* live in."""
    return doc_path(repo_dir, dt, branch, stage=stage).parent


def stage_of(repo_dir: Path, dt: DocType, branch: str) -> str | None:
    """Which stage the branch's dir currently lives in, or None."""
    for stage in STAGES:
        if branch_dir(repo_dir, dt, branch, stage).is_dir():
            return stage
    return None


def closer_target(closer_dt: DocType, repo_dir: Path, branch: str) -> Path:
    """Where the closer doc for *branch* belongs: inside the closee's dir
    at whatever stage it currently lives in. With no closee dir at all,
    the completed stage — a closer without a closee is a closed branch.
    """
    if closer_dt.closes is None:
        raise ValueError(f"'{closer_dt.key}' closes nothing")
    closee = registry()[closer_dt.closes.type]
    stage = stage_of(repo_dir, closee, branch) or STAGE_COMPLETED
    return branch_dir(repo_dir, closee, branch, stage) / closer_dt.filename


def active_branch_names(
    kb_dir: Path, scope: str, types: Iterable[DocType] | None = None,
) -> list[str]:
    """Sorted branch-dir names with an active-stage doc dir in *scope*,
    across every closable type (or just *types*)."""
    names: set[str] = set()
    for dt in closable_types() if types is None else types:
        base = kb_dir / scope / dt.dir_path / STAGE_ACTIVE
        if not base.is_dir():
            continue
        names.update(d.name for d in base.iterdir() if d.is_dir())
    return sorted(names)


def active_type_of(scope_dir: Path, branch: str) -> DocType | None:
    """The first closable type with an active-stage dir for *branch* in
    *scope_dir*, or None. Dashboards label the branch by the type that is
    actually present, not by whichever closable row comes first."""
    for dt in closable_types():
        if branch_dir(scope_dir, dt, branch, STAGE_ACTIVE).is_dir():
            return dt
    return None


def overlapping_branches(
    current_branch: str, root: Path | None = None
) -> list[tuple[str, set[str]]] | None:
    """Return (branch, overlapping_files) for each other active branch that
    shares changed files with `current_branch`.

    Queries git directly (no kb files read). Active branches are discovered
    by directory name under every closable type's active stage dir. Results
    are sorted by branch name; only branches with a non-empty overlap are
    included.

    Returns None when there is no basis for comparison (no repo root, no kb
    clone, no other active branches, or the current branch has no
    changed files vs main) — distinct from an empty list, which means the
    comparison actually ran and found no overlap.
    """
    if root is None:
        root = repo_root(quiet=True)
        if root is None:
            return None

    resolved = get_kb_dir(root)
    if resolved is None:
        return None

    other_branches: set[str] = set()
    sanitized_current = branch_dir_name(current_branch)
    for repo_dir in sorted(resolved.iterdir()):
        if not repo_dir.is_dir() or repo_dir.name.startswith((".", "_")):
            continue
        for name in active_branch_names(resolved, repo_dir.name):
            if name.startswith((".", "_")) or name == sanitized_current:
                continue
            other_branches.add(name)

    if not other_branches:
        return None

    our_files = branch_changed_files(current_branch, root)
    if not our_files:
        return None

    results: list[tuple[str, set[str]]] = []
    for other in sorted(other_branches):
        other_files = branch_changed_files(other, root)
        if not other_files:
            continue
        overlap = our_files & other_files
        if not overlap:
            continue
        results.append((other, overlap))

    return results


def overlap_line(branch: str, root: Path) -> str:
    """Return the single-line overlap summary for compact dashboards.

    None (no basis for comparison) and [] (compared, none found) both
    collapse to "none" here — the dashboards only distinguish "nothing to
    worry about" from "go check rcorn kb status".
    """
    overlaps = overlapping_branches(branch, root)
    if overlaps:
        return f"overlap: {len(overlaps)} branch(es) — see rcorn kb status"
    return "overlap: none"


def check_overlap(current_branch: str, root: Path | None = None) -> bool:
    """Warn if any other active branch has changed files that also changed here.

    Prints a multi-line block via `overlapping_branches`. Silent when there
    is no basis for comparison (see `overlapping_branches`). Returns True if
    any overlap is found.
    """
    overlaps = overlapping_branches(current_branch, root)

    if overlaps is None:
        return False

    if not overlaps:
        console.success("No overlap with other active branches.")
        print()
        return False

    console.header("Cross-branch overlap detected")
    print()
    for other, overlap in overlaps:
        console.warn(f"Branch '{other}' overlaps on {len(overlap)} file(s):")
        for f in sorted(overlap)[:5]:
            console.info(f"  {f}")
        if len(overlap) > 5:
            console.info(f"  ... and {len(overlap) - 5} more")
        print()

    return True
