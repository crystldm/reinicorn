"""rcorn kb publish — push kb changes."""

from __future__ import annotations

from reinicorn import console
from reinicorn.git import current_branch, repo_root
from reinicorn.kb import (
    commit_kb,
    ensure_kb_on_main,
    push_main_with_retry,
    report_push_failure,
    require_kb_dir,
)
from reinicorn.mode import can_publish, get_mode
from reinicorn.staging import check_overlap


def cmd_publish() -> int:
    if not can_publish():
        mode = get_mode()
        console.error(f"Publishing blocked (mode: {mode}).")
        console.next_step("rcorn mode enable")
        return 1

    root = repo_root()
    if root is None:
        return 1
    kb_dir = require_kb_dir(root)

    console.progress("Publishing kb changes...")

    if not ensure_kb_on_main(kb_dir):
        return 1

    # Auto-commit any pending changes
    commit_kb(root, "chore(kb): commit before publish", kb_dir=kb_dir)

    # Push with pull-and-retry on rejection (shared with the review lane).
    push = push_main_with_retry(kb_dir)
    if push.returncode != 0:
        report_push_failure(push, kb_dir)
        return 1

    console.success("Kb pushed to remote main.")

    branch = current_branch()
    if branch:
        check_overlap(branch, root)
    return 0
