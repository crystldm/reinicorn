"""rcorn kb sync — pull latest kb state."""

from __future__ import annotations

from reinicorn import console
from reinicorn.git import current_branch, file_transport_args, repo_root, run_git
from reinicorn.kb import (
    check_overlap,
    ensure_kb_on_main,
    require_kb_dir,
    stage_kb_pointer,
)


def cmd_sync() -> int:
    root = repo_root()
    if root is None:
        return 1
    kb_dir = require_kb_dir(root)

    console.header("Syncing kb...")
    print()

    ensure_kb_on_main(kb_dir)

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
                console.error(
                    f"Could not merge origin/main: {r.stderr.strip()}"
                )
                console.next_step("rcorn kb git status")
            return 1

    console.success("Kb synced to latest main.")

    # Stage updated pointer in parent
    stage_kb_pointer(root, kb_dir)

    print()

    branch = current_branch()
    if branch:
        check_overlap(branch, root)

    return 0
