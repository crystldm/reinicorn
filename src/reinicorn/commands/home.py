"""Bare `reinicorn` — content-first home view (axi principle 8).

Local reads only: no fetch, no network, no per-doc `git log` scans. Bare
`reinicorn` must stay near-instant; it is the orientation command.
"""

from __future__ import annotations

import sys
from pathlib import Path

from reinicorn import __version__, console
from reinicorn.config import kb_scope
from reinicorn.git import current_branch, repo_root
from reinicorn.kb import active_plan_names, branch_dir_name, get_kb_dir, overlap_line


def _bin_path() -> str:
    exe = Path(sys.argv[0]).resolve()
    try:
        return f"~/{exe.relative_to(Path.home())}"
    except ValueError:
        return str(exe)


def cmd_home() -> int:
    print(f"bin: {_bin_path()}")
    print(f"rcorn {__version__} — agentic engineering knowledgebase CLI")

    root = repo_root(quiet=True)
    if root is None:
        print("repo: not inside a git repository")
        console.next_step("rcorn help")
        return 0

    kb_dir = get_kb_dir(root)
    if kb_dir is None:
        print("kb: not set up in this repo")
        console.next_step("rcorn init", "rcorn help")
        return 0
    if not kb_dir.is_dir():
        # Fresh clone: .gitmodules declares the kb but the submodule
        # was never initialized — nothing on disk to read yet.
        print("kb: submodule not initialized")
        console.next_step("git submodule update --init kb")
        return 0

    branch = current_branch()
    print(f"branch: {branch or 'detached'}")

    plans = active_plan_names(kb_dir, kb_scope(root))
    print(f"plans: {len(plans)} active in this repo scope")

    current = branch_dir_name(branch) if branch else ""
    if branch:
        print(overlap_line(branch, root))
    if current and current in plans:
        print(f"plan: {current} (this branch)")
        console.next_step("rcorn plan show", "rcorn kb status")
    else:
        print("plan: none for this branch")
        console.next_step("rcorn plan create", "rcorn kb status")
    return 0
