"""Lifecycle verbs for closable doc types: create / status / complete.

Generated for every registry row something `closes` (today only plan).
Nothing here names a type: the row, its closer, and every path come from
the effective registry (spec: process-as-config §2).
"""

from __future__ import annotations

import re
import shutil
from datetime import date

from reinicorn import console, frontmatter
from reinicorn.config import config_get, kb_scope
from reinicorn.doc_types import DocType, closer_of, registry
from reinicorn.frontmatter import set_meta
from reinicorn.git import current_branch, repo_root, run_git
from reinicorn.identity import TICKET_PATTERN_KEY
from reinicorn.kb import commit_kb, require_kb_dir
from reinicorn.refs import dependency_placeholder
from reinicorn.staging import (
    STAGE_ACTIVE,
    STAGE_COMPLETED,
    branch_dir,
    check_overlap,
    closer_gap,
)

STATUS_COMPLETE = "complete"
STATUS_ABANDONED = "abandoned"

_TEMPLATE_DIR_NAME = "_template"


def _doc_name(dt: DocType) -> str:
    """The doc's basename from the row's filename pattern (finding: never
    assume the built-in name — an overlay may rename it)."""
    return dt.filename.rsplit("/", 1)[-1]


def cmd_lifecycle_create(doc_type: str) -> int:
    dt = registry()[doc_type]
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

    scope_dir = kb_dir / kb_scope(root)
    pdir = branch_dir(scope_dir, dt, branch, STAGE_ACTIVE)
    doc_name = _doc_name(dt)

    if pdir.is_dir():
        console.warn(f"{dt.key.capitalize()} already exists at: {pdir}/")
        console.info("Files:")
        for f in sorted(pdir.iterdir()):
            if f.is_file():
                console.info(f"  {f.name}")
        return 0

    console.header(f"Creating {dt.key} for: {branch}")
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

    rel = dt.depends_on
    template_dir = scope_dir / dt.dir_path / _TEMPLATE_DIR_NAME
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
                "[planning | in-progress | complete | abandoned]",
                dt.create_status,
            )
            target = pdir / tmpl.name
            # Aux template files (progress.md, decisions.md) are non-docs by
            # the same definition the lint rule uses: body placeholders are
            # still substituted, but no doc meta is injected and any
            # frontmatter of their own is kept as authored.
            if not frontmatter.is_doc(target):
                text = frontmatter.dumps(meta, body) if meta else body
                target.write_text(text)
                continue
            # The standard meta is injected whether or not the template has a
            # frontmatter block: a stale template must not be able to produce
            # a doc the repo's own push gate rejects. The template contributes
            # the body and any extra fields; these keys it cannot override.
            # The template owns the title wording ("Execution Plan: …");
            # the engine only substitutes the branch. A template with no
            # title gets the generic form.
            title = str(
                meta.get("title") or f"{dt.key.capitalize()}: [Branch Name]"
            ).replace("[Branch Name]", branch)
            meta.update({
                "type": dt.key,
                "title": title,
                "slug": pdir.name,
                "status": dt.create_status,
                "lifecycle": frontmatter.LIFECYCLE_ACTIVE,
                "created": date.today(),
                "author": author,
                "branch": branch,
                "ticket": ticket_id or "N/A",
                "origin": frontmatter.ORIGIN_AI,
                "human_validated": False,
            })
            # Seeded templates predating the dependency gate lack the
            # relation field; without this the created doc gives the author
            # no in-doc placeholder to fill in before the gate blocks the
            # push.
            if rel is not None:
                meta.setdefault(rel.field, dependency_placeholder(rel))
            target.write_text(frontmatter.render(meta, body))
        console.success("Created files from templates.")
    else:
        from reinicorn.commands.doc_create import render_doc
        extra: dict[str, object] = {
            "slug": pdir.name,
            "branch": branch,
            "ticket": ticket_id or "N/A",
        }
        if rel is not None:
            extra[rel.field] = dependency_placeholder(rel)
        (pdir / doc_name).write_text(render_doc(
            dt, f"{dt.key.capitalize()}: {branch}", author, extra=extra,
        ))
        console.success(f"Created minimal {doc_name} (no templates found).")

    print()
    console.info(f"{dt.key.capitalize()} directory: {pdir}/")
    for f in sorted(pdir.iterdir()):
        if f.is_file():
            console.info(f"  {f.name}")
    print()

    if ticket_id:
        console.info(f"Detected ticket: {ticket_id}")
        console.info(
            "Tip: If you have an issue tracker MCP configured, the agent can"
        )
        console.info("pull ticket details to populate it.")

    print()
    check_overlap(branch, root)
    console.success(
        f"{dt.key.capitalize()} created. Edit {pdir}/{doc_name} to add "
        "your goals and tasks."
    )

    commit_kb(root, f"{dt.key}: create {branch}", paths=[pdir])
    return 0


def cmd_lifecycle_status(doc_type: str) -> int:
    dt = registry()[doc_type]
    root = repo_root()
    if root is None:
        return 1
    kb_dir = require_kb_dir(root)

    branch = current_branch()
    if not branch:
        console.error("Not on a branch.")
        return 1

    pdir = branch_dir(kb_dir / kb_scope(root), dt, branch, STAGE_ACTIVE)

    if not pdir.is_dir():
        console.info(f"No {dt.key} for branch '{branch}'.")
        console.next_step(dt.create_hint)
        return 0

    console.header(f"{dt.key.capitalize()} status: {branch}")
    print()

    for f in sorted(pdir.glob("*.md")):
        lines = len(f.read_text().splitlines())
        console.info(f"{f.name} ({lines} lines)")

    print()

    check_overlap(branch, root)
    return 0


def cmd_lifecycle_complete(
    doc_type: str, branch: str | None = None, *,
    repo_scope: str | None = None, abandon: bool = False,
) -> int:
    """Archive a closable doc's branch dir from the active to the completed
    stage.

    Refuses (exit 1) when the row's closer is `required` and not filled —
    the next step is the closer's own create command. `abandon` is the
    escape: the doc is stamped abandoned/dropped and needs no closer.

    Args:
        doc_type: Registry key of the closable type.
        branch: Branch name to archive.  Defaults to current branch.
        repo_scope: Repo-scoped directory name.
            When None, uses the configured KB scope or origin-derived fallback.
            Pass explicitly when archiving from a different scope
            (e.g. stale-doc sweep across all repo dirs).
        abandon: Drop the doc instead of completing it.
    """
    dt = registry()[doc_type]
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
    pdir = branch_dir(scope_dir, dt, branch, STAGE_ACTIVE)
    if not pdir.is_dir():
        console.error(f"No active {dt.key} found for branch '{branch}'.")
        return 1

    closer = closer_of(dt)
    gap = closer_gap(pdir, closer) if closer is not None else None
    if (
        closer is not None and gap is not None and not abandon
        and closer.closes is not None and closer.closes.required
    ):
        console.error(
            f"{dt.key} '{branch}' cannot complete: {gap}, and its "
            f"{closer.key} is required."
        )
        console.next_step(closer.create_hint)
        console.next_step(
            f"rcorn {dt.key} complete --abandon  (drop it: no {closer.key}, "
            f"status {STATUS_ABANDONED})"
        )
        return 1

    # Mark the doc: `status` keeps the type's word, `lifecycle` is the
    # coarse axis everything queryable keys off.
    verb = "abandon" if abandon else "complete"
    doc_file = pdir / _doc_name(dt)
    if doc_file.is_file():
        doc_file.write_text(set_meta(doc_file.read_text(), {
            frontmatter.FIELD_STATUS: (
                STATUS_ABANDONED if abandon else STATUS_COMPLETE
            ),
            frontmatter.FIELD_LIFECYCLE: (
                frontmatter.LIFECYCLE_DROPPED if abandon
                else frontmatter.LIFECYCLE_DONE
            ),
        }))

    # Move from the active to the completed stage.
    completed_dir = branch_dir(scope_dir, dt, branch, STAGE_COMPLETED)
    completed_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pdir), str(completed_dir))

    console.success(
        f"{dt.key.capitalize()} {'abandoned' if abandon else 'archived'}: "
        f"{STAGE_ACTIVE}/{pdir.name}/ → {STAGE_COMPLETED}/{completed_dir.name}/"
    )

    if closer is not None and gap is not None and not abandon:
        console.warn(
            f"No {closer.key} captured for this branch — lessons "
            "learned will be lost."
        )
        console.next_step(closer.create_hint)

    # Both dirs: the deletion from the active stage and the addition under
    # the completed one.
    commit_kb(root, f"{dt.key}: {verb} {branch}", paths=[pdir, completed_dir])
    return 0
