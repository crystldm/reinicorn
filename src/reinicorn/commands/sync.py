"""rcorn kb sync — pull latest kb state."""

from __future__ import annotations

from reinicorn import console
from reinicorn.config import KB_DIR_NAME
from reinicorn.git import (
    current_branch,
    file_transport_args,
    repo_root,
    report_failure,
    run_git,
)
from reinicorn.kb import (
    check_overlap,
    checkout_kb_main,
    get_kb_dir,
    require_kb_dir,
)
from reinicorn.kb_remote import resolve_kb_remote_url
from reinicorn.kb_setup import KbSetupError, setup_kb_clone


def cmd_sync() -> int:
    root = repo_root()
    if root is None:
        return 1

    kb_dir = get_kb_dir(root)
    if kb_dir is None:
        url = resolve_kb_remote_url(root)
        if not url:
            console.error(
                f"No kb at {KB_DIR_NAME}/ and no recorded remote to clone from.\n"
                f"  How to fix: run 'rcorn init' to set up the kb."
            )
            return 1
        console.progress("No kb clone found — cloning...")
        try:
            setup_kb_clone(root, url)
        except KbSetupError as e:
            console.error(str(e))
            return 1
    kb_dir = require_kb_dir(root)

    console.header("Syncing kb...")
    print()

    if not checkout_kb_main(kb_dir):
        return 1

    # Fetch and merge latest (file_transport_args handles local remotes on git 2.38+)
    fta = file_transport_args(cwd=kb_dir)
    run_git(*fta, "fetch", "origin", "main", check=False, cwd=kb_dir)
    r = run_git("merge", "origin/main", "--ff-only", check=False, cwd=kb_dir)
    if r.returncode != 0:
        r = run_git("merge", "origin/main", check=False, cwd=kb_dir)
        if r.returncode != 0:
            conflicts = run_git(
                "diff", "--name-only", "--diff-filter=U",
                check=False, cwd=kb_dir,
            ).stdout.strip()
            if conflicts:
                console.error(
                    "Merge of origin/main hit conflicts in kb/:\n"
                    + "\n".join(f"  {f}" for f in conflicts.splitlines())
                )
                console.info(
                    "Resolve the conflicted files first — publishing before "
                    "that would commit the conflict markers."
                )
                console.next_step("rcorn kb publish")
            else:
                # Merge failed without conflicts: offline fetch, missing
                # origin/main, unrelated histories, ...
                report_failure("merge origin/main into kb", r)
                console.next_step("rcorn kb git status")
            return 1

    console.success("Kb synced to latest main.")

    print()

    branch = current_branch()
    if branch:
        check_overlap(branch, root)

    return 0
