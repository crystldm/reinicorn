"""rcorn _post-checkout — git hook logic."""

from __future__ import annotations

import re
from pathlib import Path

from reinicorn import console
from reinicorn.config import KB_DIR_NAME, config_get
from reinicorn.git import current_branch, repo_root, report_failure, run_git
from reinicorn.identity import TICKET_PATTERN_KEY
from reinicorn.kb import ensure_kb_on_main, get_kb_dir
from reinicorn.kb_remote import apply_kb_remote_url, resolve_kb_remote_url
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


def _init_kb(root: Path, kb_dir: Path) -> None:
    """Create the kb for a fresh clone or a new worktree.

    Reports failures instead of swallowing them — this is the site where a
    broken kb remote used to be installed with no signal at all, surfacing
    only at publish time after the work was done. It still never raises: a
    post-checkout hook that throws would fail the user's checkout, and a
    missing kb is recoverable while a failed `git checkout` is disruptive.
    """
    # Resolve before creating the kb: afterwards the new clone is itself an
    # "existing kb", and it carries the recorded URL we are trying to look past.
    try:
        remote = resolve_kb_remote_url(root)
        r = run_git(
            "submodule", "update", "--init",
            *_kb_reference_args(root),
            KB_DIR_NAME, cwd=root, check=False,
        )
        if r.returncode != 0:
            report_failure("initialize the kb", r, warn=True)
            console.next_step("rcorn kb sync")
            return
        # The clone above takes its URL from submodule.kb.url, which git copied
        # out of .gitmodules — so it loses any local override and can land on a
        # protocol this machine cannot authenticate with. Reads still work
        # (objects are borrowed via --reference), so without this the breakage
        # would only surface at publish time.
        if apply_kb_remote_url(kb_dir, remote) == "failed":
            # apply_kb_remote_url has already reported the cause and the fix.
            # Say what it means for the kb that was just created, and carry on:
            # the kb is usable for reads, only publishing is at risk.
            console.warn(
                f"{KB_DIR_NAME}/ was created but its remote could not be set — "
                "publishing from here will fail until it is."
            )
        ensure_kb_on_main(kb_dir)  # avoid a detached HEAD
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
    kb_dir = get_kb_dir(root)
    if kb_dir is not None:
        kb_empty = not kb_dir.is_dir() or not any(kb_dir.iterdir())
        if kb_empty:
            _init_kb(root, kb_dir)

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
