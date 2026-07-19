"""rcorn _post-checkout — git hook logic."""

from __future__ import annotations

import contextlib
import re
from pathlib import Path

from reinicorn.config import KB_DIR_NAME, config_get
from reinicorn.git import current_branch, repo_root, run_git
from reinicorn.identity import TICKET_PATTERN_KEY
from reinicorn.kb import ensure_kb_on_main, get_kb_dir, stage_kb_pointer
from reinicorn.mode import hook_check


def _kb_reference_args(root: Path) -> list[str]:
    """`git submodule update` args that borrow kb objects from the shared module.

    In a linked worktree, <git-common-dir>/modules/kb already holds every kb
    object, so cloning with --reference avoids re-fetching over the network.
    Returns [] when no usable shared module exists — on a fresh clone that
    path is the module dir about to be created, so a plain --init is correct
    there, and a module dir without objects/ would make the clone error out
    where plain --init would have worked.
    """
    r = run_git("rev-parse", "--git-common-dir", cwd=root, check=False)
    if r.returncode != 0:
        return []
    common = Path(r.stdout.strip())
    if not common.is_absolute():
        common = root / common
    ref = (common / "modules" / KB_DIR_NAME).resolve()
    if (ref / "objects").is_dir():
        return ["--reference", str(ref)]
    return []


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
                run_git(
                    "submodule", "update", "--init",
                    *_kb_reference_args(root),
                    KB_DIR_NAME, cwd=root, check=False,
                )
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
