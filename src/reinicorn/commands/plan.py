"""rcorn plan create / plan status / plan complete."""

from __future__ import annotations

import re
import shutil
from datetime import date

from reinicorn import console
from reinicorn.config import config_get, kb_scope
from reinicorn.doc_types import REGISTRY
from reinicorn.git import current_branch, repo_root, run_git
from reinicorn.identity import TICKET_PATTERN_KEY
from reinicorn.kb import branch_doc_path, check_overlap, commit_kb, plan_dir, require_kb_dir

_EMPTY_RETRO_LINE = re.compile(r"^\s*-\s*(\[ \]\s*)?(_[^_]*_)?\s*$")


def _retro_is_empty(text: str) -> bool:
    """True when a retro has no filled-in bullet content."""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("**"):
            continue
        if _EMPTY_RETRO_LINE.match(line):
            continue
        return False
    return True


def cmd_plan_create() -> int:
    root = repo_root()
    if root is None:
        return 1
    kb_dir = require_kb_dir(root)

    branch = current_branch()
    if not branch:
        console.error("Not on a branch (detached HEAD).")
        return 1

    if branch in ("main", "master"):
        console.error("You are on the default branch. Create a feature branch first.")
        return 1

    pdir = plan_dir(kb_dir, branch)

    if pdir.is_dir():
        console.warn(f"Plan already exists at: {pdir}/")
        console.info("Files:")
        for f in sorted(pdir.iterdir()):
            if f.is_file():
                console.info(f"  {f.name}")
        return 0

    console.header(f"Creating execution plan for: {branch}")
    print()

    pdir.mkdir(parents=True, exist_ok=True)

    try:
        author = run_git("config", "user.name").stdout.strip()
    except Exception:
        author = "unknown"
    date_today = date.today().isoformat()

    ticket_pattern = config_get(TICKET_PATTERN_KEY, r"[A-Z]+-[0-9]+", root)
    m = re.search(ticket_pattern, branch)
    ticket_id = m.group(0) if m else ""

    template_dir = kb_dir / kb_scope(root) / REGISTRY["plan"].dir_path / "_template"
    if template_dir.is_dir():
        for tmpl in sorted(template_dir.glob("*.md")):
            content = tmpl.read_text()
            content = content.replace("[Branch Name]", branch)
            content = content.replace("[TICKET-ID or N/A]", ticket_id or "N/A")
            content = content.replace("[developer or agent]", author)
            content = content.replace("[date]", date_today)
            content = content.replace(
                "[planning | in-progress | complete | abandoned]", "planning"
            )
            (pdir / tmpl.name).write_text(content)
        console.success("Created plan files from templates.")
    else:
        (pdir / "plan.md").write_text(
            f"# Execution Plan: {branch}\n\n"
            f"**Author:** {author}\n"
            f"**Date:** {date_today}\n"
            f"**Ticket:** {ticket_id or 'N/A'}\n"
            f"**Status:** planning\n"
        )
        console.success("Created minimal plan.md (no templates found).")

    print()
    console.info(f"Plan directory: {pdir}/")
    for f in sorted(pdir.iterdir()):
        if f.is_file():
            console.info(f"  {f.name}")
    print()

    if ticket_id:
        console.info(f"Detected ticket: {ticket_id}")
        console.info(
            "Tip: If you have an issue tracker MCP configured, the agent can"
        )
        console.info("pull ticket details to populate the plan.")

    print()
    check_overlap(branch, root)
    console.success(f"Plan created. Edit {pdir}/plan.md to add your goals and tasks.")

    commit_kb(root, f"plan: create {branch}")
    return 0


def cmd_plan_status() -> int:
    root = repo_root()
    if root is None:
        return 1
    kb_dir = require_kb_dir(root)

    branch = current_branch()
    if not branch:
        console.error("Not on a branch.")
        return 1

    pdir = plan_dir(kb_dir, branch)

    if not pdir.is_dir():
        console.info(f"No execution plan for branch '{branch}'.")
        console.next_step("rcorn plan create")
        return 0

    console.header(f"Plan status: {branch}")
    print()

    for f in sorted(pdir.glob("*.md")):
        lines = len(f.read_text().splitlines())
        console.info(f"{f.name} ({lines} lines)")

    print()

    check_overlap(branch, root)
    return 0


def cmd_plan_complete(branch: str | None = None, *, repo_scope: str | None = None) -> int:
    """Archive an execution plan from active/ to completed/.

    Args:
        branch: Branch name to archive.  Defaults to current branch.
        repo_scope: Repo-scoped directory name.
            When None, uses the configured KB scope or origin-derived fallback.
            Pass explicitly when archiving plans from a different scope
            (e.g. stale-plan sweep across all repo dirs).
    """
    root = repo_root()
    if root is None:
        return 1
    kb_dir = require_kb_dir(root)

    scope = repo_scope or kb_scope(root)

    if branch is None:
        branch = current_branch()
        if not branch:
            console.error("Not on a branch (detached HEAD).")
            return 1

    scope_dir = kb_dir / scope
    pdir = branch_doc_path("plan", scope_dir, branch).parent
    if not pdir.is_dir():
        console.error(f"No active plan found for branch '{branch}'.")
        return 1

    # Update plan.md status to complete
    plan_file = pdir / "plan.md"
    if plan_file.is_file():
        content = plan_file.read_text()
        content = re.sub(
            r"\*\*Status:\*\*\s*(planning|in-progress)",
            "**Status:** complete",
            content,
        )
        plan_file.write_text(content)

    # Move from active/ to completed/
    completed_dir = branch_doc_path("retro", scope_dir, branch).parent
    completed_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pdir), str(completed_dir))

    console.success(f"Plan archived: active/{pdir.name}/ → completed/{completed_dir.name}/")

    retro = completed_dir / "retro.md"
    if not retro.is_file() or _retro_is_empty(retro.read_text()):
        console.warn("No retro captured for this branch — lessons learned will be lost.")
        console.next_step("rcorn retro create")

    commit_kb(root, f"plan: complete {branch}")
    return 0
