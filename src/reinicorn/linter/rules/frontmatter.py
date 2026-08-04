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
        for path in sorted(kb.rglob("*.md")):
            # Scope dirs starting with "." or "_" hold generated or shared
            # material, not authored docs.
            rel_parts = path.relative_to(kb).parts
            if rel_parts and rel_parts[0].startswith((".", "_")):
                continue
            if rel_parts and rel_parts[0] == "generated":
                continue
            if not frontmatter.is_doc(path):
                continue

            rel = path.relative_to(project_root)
            meta, _ = frontmatter.read(path)
            if not meta:
                diagnostics.append(
                    f"{rel}:1 — No frontmatter block. Create docs with "
                    f"'rcorn <type> create' so the schema is applied."
                )
                continue
            diagnostics.extend(
                f"{rel}:1 — {error}" for error in frontmatter.validate(meta)
            )

        return diagnostics
