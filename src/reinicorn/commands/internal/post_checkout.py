"""rcorn _post-checkout — git hook logic."""

from __future__ import annotations

import contextlib
import re

from reinicorn.config import KB_DIR_NAME, config_get
from reinicorn.git import current_branch, repo_root, run_git
from reinicorn.identity import TICKET_PATTERN_KEY
from reinicorn.kb import ensure_kb_on_main, get_kb_dir, stage_kb_pointer
from reinicorn.mode import hook_check


def cmd_post_checkout(args: list[str]) -> int:
    checkout_type = args[2] if len(args) > 2 else "0"
    if checkout_type != "1":
        return 0

    if not hook_check():
        return 0

    root = repo_root(quiet=True)
    if root is None:
        return 0

    # Ensure kb submodule exists (fresh clone / new worktree only)
    kb_dir = get_kb_dir(root)
    if kb_dir is not None:
        kb_empty = not kb_dir.is_dir() or not any(kb_dir.iterdir())
        if kb_empty:
            with contextlib.suppress(Exception):
                run_git("submodule", "update", "--init", KB_DIR_NAME, cwd=root, check=False)
                # checkout main after init (avoid detached HEAD)
                ensure_kb_on_main(kb_dir)
                stage_kb_pointer(root, kb_dir)

    # New branch detection
    branch = current_branch()
    if not branch:
        return 0

    try:
        r = run_git(
            "for-each-ref", "--format=%(upstream:short)",
            f"refs/heads/{branch}", check=False,
        )
        upstream = r.stdout.strip()
    except Exception:
        upstream = ""

    if not upstream:
        ticket_pattern = config_get(
            TICKET_PATTERN_KEY, r"[A-Z]+-[0-9]+", root,
        )
        m = re.search(ticket_pattern, branch)
        ticket_id = m.group(0) if m else ""

        print()
        if ticket_id:
            print(f"reinicorn: new branch '{branch}' (ticket: {ticket_id})")
            print(
                f"  Run 'rcorn plan create' to set up an execution plan "
                f"with {ticket_id} context."
            )
        else:
            print(f"reinicorn: new branch '{branch}'")
            print(
                "  Run 'rcorn plan create' to set up an execution plan "
                "for this work."
            )
        print()

    return 0
