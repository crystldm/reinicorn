"""rcorn _post-checkout — git hook logic."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from reinicorn import console
from reinicorn.config import KB_DIR_NAME, config_get
from reinicorn.git import current_branch, repo_root, report_failure, run_git
from reinicorn.identity import TICKET_PATTERN_KEY
from reinicorn.kb import checkout_kb_main, get_kb_dir
from reinicorn.kb_remote import apply_kb_remote_url, resolve_kb_remote_url
from reinicorn.mode import hook_check

if TYPE_CHECKING:
    from pathlib import Path


def _clone_reference_args(root: Path) -> list[str]:
    """`git clone` args that borrow kb objects from the main checkout's kb.

    A new linked worktree clones its own kb; --reference-if-able borrows
    objects from the main checkout's clone when one exists (no network
    cost for history), --dissociate copies them so the new kb never
    depends on the other clone staying alive. Falls back to a plain
    clone when there is nothing to borrow.
    """
    from reinicorn.kb_remote import _main_checkout_root
    ref = _main_checkout_root(root) / KB_DIR_NAME
    if (ref / ".git").exists():
        return ["--reference-if-able", str(ref), "--dissociate"]
    return []


def _init_kb(root: Path) -> None:
    """Create the kb for a fresh clone or a new worktree.

    Reports failures instead of swallowing them — this is the site where a
    broken kb remote used to be installed with no signal at all, surfacing
    only at publish time after the work was done. It still never raises: a
    post-checkout hook that throws would fail the user's checkout, and a
    missing kb is recoverable while a failed `git checkout` is disruptive.
    """
    # Resolve before creating the kb: afterwards the new clone is itself an
    # "existing kb", and it carries the recorded URL we are trying to look past.
    kb_dir = root / KB_DIR_NAME
    try:
        remote = resolve_kb_remote_url(root)
        file_allow = (
            ("-c", "protocol.file.allow=always") if remote.startswith("/") else ()
        )
        r = run_git(
            *file_allow, "clone",
            *_clone_reference_args(root),
            remote, str(kb_dir), check=False,
        )
        if r.returncode != 0:
            report_failure("initialize the kb", r, warn=True)
            console.next_step("rcorn kb sync")
            return
        # The clone above already used `remote` as origin, so this is normally
        # a no-op — it exists to catch and report the case where git accepted
        # the clone but the origin ended up wrong (or unset), rather than
        # leaving that to surface silently at publish time.
        if apply_kb_remote_url(kb_dir, remote) == "failed":
            # apply_kb_remote_url has already reported the cause and the fix.
            # Say what it means for the kb that was just created, and carry on:
            # the kb is usable for reads, only publishing is at risk.
            console.warn(
                f"{KB_DIR_NAME}/ was created but its remote could not be set — "
                "publishing from here will fail until it is."
            )
        checkout_kb_main(kb_dir)  # avoid a detached HEAD
    except Exception as e:
        # Broad on purpose: a post-checkout hook that raises fails the user's
        # `git checkout`. Report and continue — a missing kb is recoverable,
        # a failed checkout is disruptive. What is NOT acceptable is silence,
        # which is what this used to do.
        console.warn(f"Could not set up {KB_DIR_NAME}/: {e}")
        console.next_step("rcorn kb sync")


def cmd_post_checkout(args: list[str]) -> int:
    checkout_type = args[2] if len(args) > 2 else "0"
    if checkout_type != "1":
        return 0

    if not hook_check():
        return 0

    root = repo_root(quiet=True)
    if root is None:
        return 0

    # Ensure kb exists (fresh clone / new worktree only)
    if get_kb_dir(root) is None and resolve_kb_remote_url(root):
        _init_kb(root)

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
