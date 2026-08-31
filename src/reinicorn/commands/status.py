"""rcorn kb status — kb health report."""

from __future__ import annotations

import time
from pathlib import Path

from reinicorn import console
from reinicorn.config import KB_DIR_NAME, config_get, kb_scope
from reinicorn.doc_types import closable_types, registry
from reinicorn.git import current_branch, repo_root, run_git
from reinicorn.hooks_health import hook_issues
from reinicorn.identity import STALE_THRESHOLD_KEY
from reinicorn.kb import branch_dir_name, require_kb_dir
from reinicorn.review import collect_gated_drafts
from reinicorn.staging import (
    STAGE_ACTIVE,
    active_branch_names,
    check_overlap,
    overlap_line,
)


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

    # Count active branch docs of every closable type, across all repos
    for dt in closable_types():
        active_dirs = []
        for repo_dir in sorted(kb_dir.iterdir()):
            if not repo_dir.is_dir() or repo_dir.name.startswith((".", "_")):
                continue
            active_dir = repo_dir / dt.dir_path / STAGE_ACTIVE
            if active_dir.is_dir():
                active_dirs.extend(
                    d for d in active_dir.iterdir() if d.is_dir()
                )
        if active_dirs:
            console.info(f"Active {dt.key}s: {len(active_dirs)}")
            sanitized = branch_dir_name(branch) if branch else ""
            for d in sorted(active_dirs, key=lambda p: p.name):
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
        from reinicorn.staging import branch_dir
        scope_dir = kb_dir / kb_scope(root)
        for dt in closable_types():
            if branch_dir(scope_dir, dt, branch, STAGE_ACTIVE).is_dir():
                console.success(f"Current branch has a {dt.key}.")
            else:
                console.warn(f"Current branch has no {dt.key}.")
                console.next_step(dt.create_hint)
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

    _report_hook_health(root)
    _report_pointer_drift(root, kb_dir)

    # Index-file dashboard lines: one per row with an index, first repo
    # scope that has any.
    for repo_dir in sorted(kb_dir.iterdir()):
        if not repo_dir.is_dir() or repo_dir.name.startswith((".", "_")):
            continue
        found = False
        for dt in registry().values():
            if dt.index_file is None:
                continue
            index = repo_dir / dt.dir_path / dt.index_file
            if index.is_file():
                found = True
                rel = f"{KB_DIR_NAME}/{repo_dir.name}/{dt.dir_path}/{dt.index_file}"
                console.info(f"{dt.readme_label or dt.key}: see {rel}")
        if found:
            break
    print()

    return 0


def _report_hook_health(root: Path) -> None:
    """Warn about installed git hooks whose kb guard is silently dead —
    stale reins-era hooks or an unreachable reinicorn marker (issue #24)."""
    r = run_git("rev-parse", "--git-common-dir", check=False, cwd=root)
    if r.returncode != 0:
        return
    git_dir = Path(r.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = root / git_dir
    issues = hook_issues(git_dir / "hooks")
    for issue in issues:
        console.warn(f"Hook {issue.name}: {issue.problem}")
    if issues:
        console.next_step("rcorn hooks install")


def _report_pointer_drift(root: Path, kb_dir: Path) -> None:
    """Warn when the parent's recorded kb pointer is behind kb origin/main.

    Local refs only (principle 6: no network in status) — drift shows as of
    the last fetch/push, which is exactly when it silently accumulates.
    """
    r = run_git("rev-parse", f"HEAD:{KB_DIR_NAME}", check=False, cwd=root)
    if r.returncode != 0:
        return
    recorded = r.stdout.strip()
    if not recorded:
        return
    r = run_git(
        "rev-list", "--count", f"{recorded}..origin/main",
        check=False, cwd=kb_dir,
    )
    if r.returncode != 0:
        return
    try:
        behind = int(r.stdout.strip())
    except ValueError:
        return
    if behind > 0:
        console.warn(
            f"Parent kb pointer is {behind} commit(s) behind kb origin/main."
        )
        console.next_step("rcorn kb sync")


def _compact_status(root: Path, kb_dir: Path, branch: str) -> int:
    """≤10-line undecorated dashboard for session-start context injection.

    No stale scan (per-doc `git log` is too slow for every session) and no
    headers — this output loads into agent context every session.
    """
    names = active_branch_names(kb_dir, kb_scope(root))
    current = branch_dir_name(branch) if branch else ""
    has_doc = current in names
    closable = closable_types()
    label = closable[0].key if closable else "doc"
    state = f"{label} present" if has_doc else f"no {label}"
    print(f"reinicorn: branch {branch or 'detached'} — {state}")
    print(f"{label}s: {len(names)} active in this repo scope")

    print(overlap_line(branch, root) if branch else "overlap: none")

    if not closable:
        return 0
    if has_doc:
        console.next_step(f"rcorn {label} show")
    else:
        console.next_step(closable[0].create_hint)
    return 0
