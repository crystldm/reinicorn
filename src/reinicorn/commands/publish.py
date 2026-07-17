"""rcorn kb publish — push kb changes."""

from __future__ import annotations

from reinicorn import console
from reinicorn.git import current_branch, repo_root
from reinicorn.kb import (
    check_overlap,
    commit_kb,
    ensure_kb_on_main,
    push_main_with_retry,
    require_kb_dir,
    stage_kb_pointer,
)
from reinicorn.mode import can_publish, get_mode


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

    ensure_kb_on_main(kb_dir)

    # Auto-commit any pending changes
    commit_kb(root, "chore(kb): commit before publish", kb_dir=kb_dir)

    # Push with pull-and-retry on rejection (shared with the review lane).
    push = push_main_with_retry(kb_dir)
    if push.returncode != 0:
        console.error(
            "Publish failed — kb has conflicting changes. "
            "Resolve any conflicts in kb/, then retry."
        )
        console.next_step("rcorn kb publish")
        return 1

    console.success("Kb pushed to remote main.")

    # Stage parent pointer (picked up by next parent commit)
    stage_kb_pointer(root, kb_dir)

    branch = current_branch()
    if branch:
        check_overlap(branch, root)
    return 0
