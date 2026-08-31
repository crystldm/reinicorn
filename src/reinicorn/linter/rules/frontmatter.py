"""Lint rule: every kb doc carries valid frontmatter.

Replaces the `kb/provenance` shell rule, which grepped the first ten lines
for `author:`/`status:`/`origin:` and could not tell a real field from the
word appearing in prose. This runs the same `frontmatter.validate` the create
paths run, so CI and creation cannot drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from reinicorn import frontmatter
from reinicorn.config import KB_DIR_NAME
from reinicorn.corpus import iter_docs
from reinicorn.linter.rules.base import LintRule

if TYPE_CHECKING:
    from pathlib import Path


class FrontmatterRule(LintRule):
    def name(self) -> str:
        return f"{KB_DIR_NAME}/frontmatter"

    def run(self, project_root: Path) -> list[str]:
        kb = project_root / KB_DIR_NAME
        if not kb.is_dir():
            return []

        diagnostics: list[str] = []
        for doc in iter_docs(kb):
            rel = doc.path.relative_to(project_root)
            if not doc.meta:
                diagnostics.append(
                    f"{rel}:1 — No frontmatter block. Create docs with "
                    f"'rcorn <type> create' so the schema is applied."
                )
                continue
            diagnostics.extend(
                f"{rel}:1 — {error}"
                for error in frontmatter.validate(doc.meta, project_root)
            )

        return diagnostics
