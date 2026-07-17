"""rcorn kb — manage repo scopes in the shared kb."""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

from reinicorn import console
from reinicorn.config import KB_DIR_NAME
from reinicorn.git import file_transport_args, run_git
from reinicorn.kb import require_kb_dir
from reinicorn.validation import is_valid_scope_name

if TYPE_CHECKING:
    from pathlib import Path


def _list_scopes(kb_dir: Path) -> list[str]:
    """Return sorted list of repo-scoped directory names in the kb."""
    return sorted(
        d.name
        for d in kb_dir.iterdir()
        if d.is_dir() and not d.name.startswith((".", "_"))
    )


def cmd_kb_list(*, kb_dir: Path | None = None) -> int:
    """List all repo-scoped directories in the kb."""
    if kb_dir is None:
        kb_dir = require_kb_dir()

    scopes = _list_scopes(kb_dir)

    console.header("Kb Scopes")
    print()
    if not scopes:
        console.info("No repo scopes found in kb.")
        return 0

    for name in scopes:
        console.info(f"  {name}/")
    print()
    console.info(f"{len(scopes)} scope(s) total")
    return 0


def cmd_kb_remove_scope(
    name: str,
    *,
    kb_dir: Path | None = None,
    push: bool = True,
    force: bool = False,
) -> int:
    """Remove a repo-scoped directory from the kb."""
    if "/" in name or "\\" in name:
        console.error(
            f"Invalid scope name '{name}': must not contain path separators.\n"
            f"  How to fix: Use a simple name like 'my-project'"
        )
        return 1

    # Reject empty, traversal, leading '.'/'_'/'-', whitespace, and control
    # characters before any name reaches the filesystem. An empty name would
    # otherwise resolve to the kb root and delete the entire local kb.
    if not is_valid_scope_name(name):
        console.error(
            f"Invalid scope name '{name}'.\n"
            f"  A scope must start with a letter or digit and contain only\n"
            f"  letters, digits, '.', '-', or '_'.\n"
            f"  How to fix: Check the scope name with 'rcorn kb list'"
        )
        return 1

    if kb_dir is None:
        kb_dir = require_kb_dir()

    scope_dir = kb_dir / name
    if not scope_dir.is_dir():
        console.error(
            f"Scope '{name}' not found in kb.\n"
            f"  Available scopes: {', '.join(_list_scopes(kb_dir)) or '(none)'}\n"
            f"  How to fix: Check the scope name with 'rcorn kb list'"
        )
        return 1

    if not force:
        if not sys.stdout.isatty():
            console.error(
                f"Refusing to remove {KB_DIR_NAME}/{name}/ non-interactively "
                f"without --force.\n"
                f"  How to fix: Rerun with --force to confirm the removal."
            )
            return 1
        answer = input(f"  Remove {KB_DIR_NAME}/{name}/ and push? [y/N] ").strip().lower()
        if answer != "y":
            console.info("Cancelled.")
            return 0

    shutil.rmtree(scope_dir)
    console.success(f"Removed {KB_DIR_NAME}/{name}/")

    run_git("add", "-A", cwd=kb_dir)
    r = run_git(
        "commit", "-q", "-m", f"chore: remove kb scope '{name}'",
        check=False, cwd=kb_dir,
    )
    if r.returncode != 0:
        console.warn("No tracked files to commit (scope may have been untracked)")

    if push:
        try:
            ft = file_transport_args(cwd=kb_dir)
            run_git(*ft, "push", "-q", "origin", "HEAD", cwd=kb_dir)
            console.success("Pushed to remote")
        except subprocess.CalledProcessError as e:
            console.warn(f"Could not push: {e.stderr or e}")
            console.warn(f"Push the kb manually: cd {KB_DIR_NAME} && git push")

    return 0
