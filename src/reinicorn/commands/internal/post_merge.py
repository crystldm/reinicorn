"""rcorn _post-merge — archive stale plans after merge."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from reinicorn.doc_types import REGISTRY
from reinicorn.git import repo_root, run_git
from reinicorn.kb import branch_dir_name, get_kb_dir
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

        # Build set of sanitized remote branch names for comparison
        live_branches = _live_remote_branches_sanitized(root)
        if live_branches is None:
            return  # error querying remote — don't archive anything

        for entry in sorted(active_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if not any(entry.glob("*.md")):
                continue
            if entry.name in live_branches:
                continue
            # No remote branch maps to this dir — archive the plan
            with contextlib.suppress(Exception):
                from reinicorn.commands.plan import cmd_plan_complete
                cmd_plan_complete(entry.name, repo_scope=repo_dir.name)


def _live_remote_branches_sanitized(root: Path) -> set[str] | None:
    """Return the set of remote branch names, sanitized to match dir names.

    Returns None on error so the caller can bail out safely (don't archive).
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
            branches.add(branch_dir_name(name))
        return branches
    except Exception:
        return None
