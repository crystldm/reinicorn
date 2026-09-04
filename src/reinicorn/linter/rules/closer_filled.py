"""Lint rule ``kb/closer-filled``: an active closee whose row has a
*required* closer must have that closer present and filled in.

Reads only the ``closes`` relation (spec: process-as-config §3). With the
shipped defaults nothing is required, so the rule passes untouched until
an overlay — or the stage-4 defaults flip — says otherwise. The filled
check is `staging.closer_gap`, the same one `complete` refuses on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from reinicorn.config import KB_DIR_NAME
from reinicorn.corpus import iter_branch_dirs
from reinicorn.doc_types import closable_types, closer_of
from reinicorn.linter.rules.base import LintRule
from reinicorn.staging import STAGE_ACTIVE, closer_gap

if TYPE_CHECKING:
    from pathlib import Path


class CloserFilledRule(LintRule):
    def name(self) -> str:
        return f"{KB_DIR_NAME}/closer-filled"

    def run(self, project_root: Path) -> list[str]:
        kb = project_root / KB_DIR_NAME
        if not kb.is_dir():
            return []

        diagnostics: list[str] = []
        for dt in closable_types(project_root):
            closer = closer_of(dt, project_root)
            if closer is None or closer.closes is None or not closer.closes.required:
                continue
            doc_name = dt.filename.rsplit("/", 1)[-1]
            for _scope, stage_dir in iter_branch_dirs(kb, dt, STAGE_ACTIVE):
                gap = closer_gap(stage_dir, closer)
                if gap is None:
                    continue
                rel_doc = (stage_dir / doc_name).relative_to(project_root)
                diagnostics.append(
                    f"{rel_doc}:1 — active {dt.key} '{stage_dir.name}' has "
                    f"no filled {closer.key}: {gap} — {closer.create_hint}"
                )
        return diagnostics
