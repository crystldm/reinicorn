"""rcorn kb lint — run kb lint rules."""

from __future__ import annotations

from reinicorn.git import repo_root
from reinicorn.kb import require_kb_dir
from reinicorn.linter.runner import run_lints


def cmd_lint() -> int:
    root = repo_root()
    if root is None:
        return 1
    require_kb_dir(root)
    return run_lints(root)
