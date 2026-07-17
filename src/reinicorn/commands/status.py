"""rcorn kb status — kb health report."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from reinicorn import console
from reinicorn.config import KB_DIR_NAME, config_get, kb_scope
from reinicorn.doc_types import REGISTRY
from reinicorn.git import current_branch, repo_root, run_git
from reinicorn.identity import STALE_THRESHOLD_KEY
from reinicorn.kb import (
    active_plan_names,
    branch_dir_name,
    check_overlap,
    overlap_line,
    require_kb_dir,
)
from reinicorn.review import collect_gated_drafts

if TYPE_CHECKING:
    from pathlib import Path


def cmd_status(compact: bool = False) -> int:
    root = repo_root()
    if root is None:
        return 1
    kb_dir = require_kb_dir(root)
    branch = current_branch()

    if compact:
        return _compact_status(root, kb_dir, branch)

    console.header("Reinicorn Kb Status")
    print()
    console.info(f"Kb: {kb_dir}")
    console.info(f"Branch: {branch or 'detached'}")
    print()

    # Count active plans across all repos
    plan_dirs = []
    for repo_dir in sorted(kb_dir.iterdir()):
        if not repo_dir.is_dir() or repo_dir.name.startswith((".", "_")):
            continue
        active_dir = repo_dir / REGISTRY["plan"].dir_path / "active"
        if active_dir.is_dir():
            plan_dirs.extend(d for d in active_dir.iterdir() if d.is_dir())

    if plan_dirs:
        console.info(f"Active execution plans: {len(plan_dirs)}")
        sanitized = branch_dir_name(branch) if branch else ""
        for d in sorted(plan_dirs, key=lambda p: p.name):
            if d.name == sanitized:
                console.info(f"  * {d.name} (current)")
            else:
                console.info(f"    {d.name}")
    print()

    # In-review / draft gated docs across all repo scopes — frontmatter-only
    # reads, no gh calls (principle 6: cross-branch visibility without network).
    reviews = [
        (repo_dir.name, row)
        for repo_dir in sorted(kb_dir.iterdir())
        if repo_dir.is_dir() and not repo_dir.name.startswith((".", "_"))
        for row in collect_gated_drafts(repo_dir)
    ]
    if reviews:
        console.info(f"In review / drafts: {len(reviews)}")
        for scope, row in reviews:
            line = f"  {scope}/{row.key}/{row.slug} [{row.status}]"
            if row.review_pr:
                line += f" {row.review_pr}"
            console.info(line)
        print()

    if branch:
        from reinicorn.kb import plan_dir
        pdir = plan_dir(kb_dir, branch)
        if pdir.is_dir():
            console.success("Current branch has an execution plan.")
        else:
            console.warn("Current branch has no execution plan.")
            console.next_step("rcorn plan create")
    print()

    if branch:
        check_overlap(branch, root)

    console.header("Health")
    print()

    threshold = int(config_get(STALE_THRESHOLD_KEY, "30", root))
    stale_count = 0
    now = time.time()

    for doc in kb_dir.rglob("*.md"):
        if "generated" in doc.parts:
            continue
        try:
            r = run_git(
                "log", "-1", "--format=%at", "--", str(doc),
                check=False, cwd=root,
            )
            last_modified = int(r.stdout.strip() or "0")
        except (ValueError, Exception):
            last_modified = 0
        age_days = int((now - last_modified) / 86400)
        if age_days > threshold:
            stale_count += 1

    if stale_count > 0:
        console.warn(f"Stale docs (>{threshold} days): {stale_count}")
    else:
        console.success("All kb docs are fresh.")

    # Check tech debt across repos
    for repo_dir in sorted(kb_dir.iterdir()):
        if not repo_dir.is_dir() or repo_dir.name.startswith((".", "_")):
            continue
        debt_file = repo_dir / REGISTRY["debt"].dir_path / "index.md"
        if debt_file.is_file():
            debt_path = f"{KB_DIR_NAME}/{repo_dir.name}/{REGISTRY['debt'].dir_path}/index.md"
            console.info(f"Tech debt: see {debt_path}")
            break
    print()

    return 0


def _compact_status(root: Path, kb_dir: Path, branch: str) -> int:
    """≤10-line undecorated dashboard for session-start context injection.

    No stale scan (per-doc `git log` is too slow for every session) and no
    headers — this output loads into agent context every session.
    """
    plans = active_plan_names(kb_dir, kb_scope(root))
    current = branch_dir_name(branch) if branch else ""
    has_plan = current in plans
    state = "plan present" if has_plan else "no plan"
    print(f"reinicorn: branch {branch or 'detached'} — {state}")
    print(f"plans: {len(plans)} active in this repo scope")

    print(overlap_line(branch, root) if branch else "overlap: none")

    if has_plan:
        console.next_step("rcorn plan show")
    else:
        console.next_step("rcorn plan create")
    return 0
