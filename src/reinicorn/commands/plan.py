"""rcorn plan create / plan status / plan complete."""

from __future__ import annotations

import re
import shutil
from datetime import date

from reinicorn import console, frontmatter
from reinicorn.config import config_get, kb_scope
from reinicorn.doc_types import REGISTRY
from reinicorn.frontmatter import set_meta
from reinicorn.git import current_branch, repo_root, run_git
from reinicorn.identity import TICKET_PATTERN_KEY
from reinicorn.kb import branch_doc_path, check_overlap, commit_kb, plan_dir, require_kb_dir

_EMPTY_RETRO_LINE = re.compile(r"^\s*-\s*(\[ \]\s*)?(_[^_]*_)?\s*$")


def _retro_is_empty(text: str) -> bool:
    """True when a retro has no filled-in bullet content.

    Reads the body only: frontmatter keys are metadata, and counting them as
    content would make every retro look filled in.
    """
    for line in frontmatter.parse(text)[1].splitlines():
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
            meta, body = frontmatter.parse(tmpl.read_text())
            # Frontmatter values are set on the parsed mapping, never by string
            # substitution: a branch containing a colon or a quote would
            # otherwise produce a corrupt YAML block.
            body = body.replace("[Branch Name]", branch)
            body = body.replace("[TICKET-ID or N/A]", ticket_id or "N/A")
            body = body.replace("[developer or agent]", author)
            body = body.replace("[date]", date_today)
            body = body.replace(
                "[planning | in-progress | complete | abandoned]", "planning"
            )
            if meta:
                meta.update({
                    "title": f"Execution Plan: {branch}",
                    "slug": pdir.name,
                    "status": "planning",
                    "lifecycle": frontmatter.LIFECYCLE_ACTIVE,
                    "created": date.today(),
                    "author": author,
                    "branch": branch,
                    "ticket": ticket_id or "N/A",
                })
                (pdir / tmpl.name).write_text(frontmatter.dumps(meta, body))
            else:
                (pdir / tmpl.name).write_text(body)
        console.success("Created plan files from templates.")
    else:
        (pdir / "plan.md").write_text(frontmatter.dumps(
            {
                "type": "plan",
                "title": f"Execution Plan: {branch}",
                "slug": pdir.name,
                "lifecycle": frontmatter.LIFECYCLE_ACTIVE,
                "status": "planning",
                "created": date.today(),
                "author": author,
                "branch": branch,
                "ticket": ticket_id or "N/A",
            },
            f"\n# Execution Plan: {branch}\n",
        ))
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

    # Mark the plan complete: `status` keeps the type's word, `lifecycle` is
    # the coarse axis everything queryable keys off.
    plan_file = pdir / "plan.md"
    if plan_file.is_file():
        plan_file.write_text(set_meta(plan_file.read_text(), {
            frontmatter.FIELD_STATUS: "complete",
            frontmatter.FIELD_LIFECYCLE: frontmatter.LIFECYCLE_DONE,
        }))

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
