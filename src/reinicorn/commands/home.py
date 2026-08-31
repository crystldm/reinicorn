"""Bare `reinicorn` — content-first home view (axi principle 8).

Local reads only: no fetch, no network, no per-doc `git log` scans. Bare
`reinicorn` must stay near-instant; it is the orientation command.
"""

from __future__ import annotations

import sys
from pathlib import Path

from reinicorn import __version__, console
from reinicorn.config import kb_scope
from reinicorn.doc_types import closable_types
from reinicorn.git import current_branch, repo_root
from reinicorn.kb import branch_dir_name, get_kb_dir
from reinicorn.kb_remote import configured_kb_remote_url
from reinicorn.staging import active_branch_names, overlap_line


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
        if configured_kb_remote_url(root):
            print("kb: not cloned yet")
            console.next_step("rcorn kb sync")
        else:
            print("kb: not set up in this repo")
            console.next_step("rcorn init", "rcorn help")
        return 0

    branch = current_branch()
    print(f"branch: {branch or 'detached'}")

    names = active_branch_names(kb_dir, kb_scope(root))
    closable = closable_types()
    label = closable[0].key if closable else "doc"
    print(f"{label}s: {len(names)} active in this repo scope")

    current = branch_dir_name(branch) if branch else ""
    if branch:
        print(overlap_line(branch, root))
    if current and current in names:
        print(f"{label}: {current} (this branch)")
        console.next_step(f"rcorn {label} show", "rcorn kb status")
    elif closable:
        print(f"{label}: none for this branch")
        console.next_step(closable[0].create_hint, "rcorn kb status")
    else:
        console.next_step("rcorn kb status")
    return 0
