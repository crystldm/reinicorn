"""Lint rule ``kb/lifecycle``: an active closee whose branch is merged or
deleted is stale — "merged/deleted but still active".

Reads the ``closes`` relation only (spec: process-as-config §3). Merged-ness
needs three signals, checked in order, because a squash merge leaves a
retained branch that is *not* an ancestor of the default branch:

1. the branch was published and is now gone from origin — deletion counts
   only with publication evidence (a stale local tracking ref, or any PR
   with that head), so a branch never pushed matches no signal;
2. ``origin/<branch>`` is an ancestor of ``origin/HEAD`` (merge-commit case);
3. a merged PR has that head (squash case, authoritative).

Every network fact fails open as "cannot verify" — a lint that reds a kb
because the network blinked would be worse than a missed stale plan. Only
the project's own scope is judged: another scope's branches belong to
another repo.
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from reinicorn import frontmatter
from reinicorn.config import KB_DIR_NAME, kb_scope
from reinicorn.doc_types import closable_types
from reinicorn.git import gh_repo_from_url, remote_url, run_git
from reinicorn.github import PR_LIST_STATE_ALL, PR_LIST_STATE_MERGED, gh_pr_heads
from reinicorn.linter.rules.base import LintRule
from reinicorn.staging import STAGE_ACTIVE, stage_root

if TYPE_CHECKING:
    from pathlib import Path

    from reinicorn.doc_types import DocType

_REMOTE = "origin"
_HEADS_PREFIX = "refs/heads/"


class MergeProbe:
    """The three merged-ness signals for one repo, each network fact fetched
    at most once per lint run and cached — including a failure, which stays
    "cannot verify" for every branch rather than being retried per doc."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._live: set[str] | None = None
        self._live_known = False
        self._pr_heads: dict[str, set[str] | None] = {}

    def merged(self, branch: str) -> bool:
        """True only when a signal positively says merged/deleted."""
        live = self.live_heads()
        if live is not None and branch not in live and self._published(branch):
            return True
        if self._is_ancestor_of_default(branch):
            return True
        merged = self.pr_heads(PR_LIST_STATE_MERGED)
        return merged is not None and branch in merged

    # --- signal 1 ---------------------------------------------------------

    def live_heads(self) -> set[str] | None:
        """Branch names on origin right now, or None when it cannot be
        asked (offline, no remote, credentials wanted)."""
        if self._live_known:
            return self._live
        self._live_known = True
        self._live = self._ls_remote_heads()
        return self._live

    def _ls_remote_heads(self) -> set[str] | None:
        # Never let a credential prompt hang a lint run: fail open instead.
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        try:
            r = subprocess.run(
                ["git", "ls-remote", "--heads", _REMOTE],
                capture_output=True, text=True, check=False,
                cwd=self._root, env=env,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        heads: set[str] = set()
        for line in r.stdout.splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2 and parts[1].startswith(_HEADS_PREFIX):
                heads.add(parts[1].removeprefix(_HEADS_PREFIX))
        return heads

    def _published(self, branch: str) -> bool:
        """Evidence the branch once existed on origin."""
        r = run_git(
            "show-ref", "--verify", "--quiet",
            f"refs/remotes/{_REMOTE}/{branch}",
            cwd=self._root, check=False,
        )
        if r.returncode == 0:
            return True
        heads = self.pr_heads(PR_LIST_STATE_ALL)
        return heads is not None and branch in heads

    # --- signal 2 ---------------------------------------------------------

    def _is_ancestor_of_default(self, branch: str) -> bool:
        r = run_git(
            "merge-base", "--is-ancestor",
            f"refs/remotes/{_REMOTE}/{branch}", f"refs/remotes/{_REMOTE}/HEAD",
            cwd=self._root, check=False,
        )
        # 0 = ancestor, 1 = not; anything else (missing ref, no origin/HEAD)
        # is "cannot verify".
        return r.returncode == 0

    # --- signal 3 ---------------------------------------------------------

    def pr_heads(self, state: str) -> set[str] | None:
        if state not in self._pr_heads:
            repo = gh_repo_from_url(remote_url(self._root))
            self._pr_heads[state] = (
                gh_pr_heads(repo, state=state) if repo else None
            )
        return self._pr_heads[state]


def _active_docs(
    scope_dir: Path, types: list[DocType],
) -> list[tuple[DocType, Path, str]]:
    """(row, doc file, branch) for every active closee doc that names a
    usable branch. A doc without a branch cannot be judged and is skipped."""
    found: list[tuple[DocType, Path, str]] = []
    for dt in types:
        doc_name = dt.filename.rsplit("/", 1)[-1]
        root = stage_root(scope_dir, dt, STAGE_ACTIVE)
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            doc = entry / doc_name
            if not doc.is_file():
                continue
            meta, _ = frontmatter.read(doc)
            branch = str(meta.get("branch") or "").strip()
            if not branch or "\n" in branch:
                continue
            found.append((dt, doc, branch))
    return found


class LifecycleRule(LintRule):
    def name(self) -> str:
        return f"{KB_DIR_NAME}/lifecycle"

    def run(self, project_root: Path) -> list[str]:
        kb = project_root / KB_DIR_NAME
        if not kb.is_dir():
            return []
        scope_dir = kb / kb_scope(project_root)
        if not scope_dir.is_dir():
            return []

        docs = _active_docs(scope_dir, closable_types(project_root))
        if not docs:
            return []

        probe = MergeProbe(project_root)
        diagnostics: list[str] = []
        for dt, doc, branch in docs:
            if not probe.merged(branch):
                continue
            rel_doc = doc.relative_to(project_root)
            diagnostics.append(
                f"{rel_doc}:1 — branch '{branch}' is merged/deleted but "
                f"still active — rcorn {dt.key} complete {branch}"
            )
        return diagnostics
