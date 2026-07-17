"""rcorn kb git — run git commands inside the kb directory."""

from __future__ import annotations

from reinicorn import console
from reinicorn.git import repo_root, run_git
from reinicorn.kb import require_kb_dir


def cmd_kb_git(args: list[str]) -> int:
    """Run a git command inside the kb submodule directory."""
    if not args:
        console.error("Usage: rcorn kb git <git-args>")
        return 1

    root = repo_root()
    if root is None:
        return 1
    kb_dir = require_kb_dir(root)

    # Go through run_git so inherited GIT_DIR/GIT_WORK_TREE (set when git invokes
    # a hook in a worktree) are stripped — otherwise git would target the parent
    # gitdir instead of the kb submodule. capture=False streams git's output to
    # the terminal; check=False forwards git's exit code to the caller.
    result = run_git(*args, capture=False, check=False, cwd=kb_dir)
    return result.returncode
