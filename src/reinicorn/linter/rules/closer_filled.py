"""Lint rule ``kb/closer-filled``: an active closee whose row has a
*required* closer must not carry an unfilled one.

Reads only the ``closes`` relation (spec: process-as-config §3). The filled
check is `staging.closer_gap`, the same one `complete` refuses on. Two
presence modes, because the closer is due at different moments:

- whole-kb (`rcorn kb lint`, the default): only a closer that exists but is
  placeholder-only is reported. A missing closer on an in-progress closee
  is normal — the retro is written inside the PR (spec §6) — so it is not
  a kb-wide finding.
- strict (``missing_counts=True``, the process gate): a missing closer is
  reported too. The gate is the pre-merge check, where the closer is due.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from reinicorn.config import KB_DIR_NAME
from reinicorn.corpus import iter_branch_dirs
from reinicorn.doc_types import closable_types, closer_of, is_required_closer
from reinicorn.linter.rules.base import LintRule
from reinicorn.staging import STAGE_ACTIVE, closer_gap

if TYPE_CHECKING:
    from pathlib import Path


class CloserFilledRule(LintRule):
    def __init__(self, *, missing_counts: bool = False) -> None:
        self.missing_counts = missing_counts

    def name(self) -> str:
        return f"{KB_DIR_NAME}/closer-filled"

    def run(self, project_root: Path) -> list[str]:
        kb = project_root / KB_DIR_NAME
        if not kb.is_dir():
            return []

        diagnostics: list[str] = []
        for dt in closable_types(project_root):
            closer = closer_of(dt, project_root)
            if closer is None or not is_required_closer(closer):
                continue
            doc_name = dt.filename.rsplit("/", 1)[-1]
            for _scope, stage_dir in iter_branch_dirs(kb, dt, STAGE_ACTIVE):
                if not self.missing_counts and not (stage_dir / closer.filename).is_file():
                    continue
                gap = closer_gap(stage_dir, closer)
                if gap is None:
                    continue
                rel_doc = (stage_dir / doc_name).relative_to(project_root)
                diagnostics.append(
                    f"{rel_doc}:1 — active {dt.key} '{stage_dir.name}' has "
                    f"no filled {closer.key}: {gap} — {closer.create_hint}"
                )
        return diagnostics
