"""rcorn _post-merge — archive stale plans after merge."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from reinicorn import frontmatter
from reinicorn.doc_types import REGISTRY
from reinicorn.git import repo_root, run_git
from reinicorn.kb import get_kb_dir
from reinicorn.mode import hook_check

if TYPE_CHECKING:
    from pathlib import Path


def cmd_post_merge() -> int:
    if not hook_check():
        return 0

    root = repo_root(quiet=True)
    if root is None:
        return 0

    _archive_stale_plans(root)

    return 0


def _archive_stale_plans(root: Path) -> None:
    """Archive active plans whose remote branches no longer exist."""
    resolved = get_kb_dir(root)
    if resolved is None:
        return

    # Iterate over all repo-scoped dirs
    for repo_dir in sorted(resolved.iterdir()):
        if not repo_dir.is_dir() or repo_dir.name.startswith((".", "_")):
            continue
        active_dir = repo_dir / REGISTRY["plan"].dir_path / "active"
        if not active_dir.is_dir():
            continue

        live_branches = _live_remote_branches(root)
        if live_branches is None:
            return  # error querying remote — don't archive anything

        for entry in sorted(active_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if not any(entry.glob("*.md")):
                continue
            # Compare the exact branch from frontmatter. Comparing sanitized
            # directory names instead is lossy and many-to-one — `/` and `\`
            # both become `-` — so a deleted `feature/mvp` plan looked alive
            # whenever an unrelated `feature-mvp` branch existed.
            meta, _ = frontmatter.read(entry / "plan.md")
            branch = str(meta.get("branch") or "").strip()
            # Archiving is destructive, so anything short of a usable ref means
            # "cannot verify", never "gone". A malformed or multi-line value
            # would otherwise match nothing in live_branches and be read as a
            # deleted branch.
            if not _usable_ref(branch, root):
                continue
            if branch in live_branches:
                continue
            # No remote branch maps to this dir — archive the plan
            with contextlib.suppress(Exception):
                from reinicorn.commands.plan import cmd_plan_complete
                cmd_plan_complete(entry.name, repo_scope=repo_dir.name)


def _usable_ref(branch: str, root: Path) -> bool:
    """Whether *branch* is a value git would accept as a branch name.

    `branch:` comes from a kb doc, so it is external input at a boundary that
    gates a destructive action.
    """
    if not branch or "\n" in branch:
        return False
    r = run_git("check-ref-format", "--branch", branch, cwd=root, check=False)
    return r.returncode == 0


def _live_remote_branches(root: Path) -> set[str] | None:
    """The set of remote branch names, exactly as git reports them.

    Not sanitized: the comparison is against the `branch:` field in plan
    frontmatter, which holds the unmodified ref. Returns None on error so the
    caller can bail out safely (don't archive).
    """
    try:
        result = run_git(
            "branch", "-r", "--list", "origin/*",
            cwd=root, check=False,
        )
        branches: set[str] = set()
        for line in result.stdout.strip().splitlines():
            name = line.strip().removeprefix("origin/")
            if " -> " in name:
                continue  # skip HEAD pointer
            branches.add(name)
        return branches
    except Exception:
        return None
