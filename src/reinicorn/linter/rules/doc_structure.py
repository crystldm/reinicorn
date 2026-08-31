"""Lint rule: validate active-stage doc structure for every closable type.

The rule's public name stays "plan-structure": rule names are enablement
keys in deployed ``linters/.lint-config.json`` files, and a silent skip is
how a renamed rule dies (the runner ignores unconfigured rules). The name
is config-compat surface, like the CLI type keys themselves.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from reinicorn.config import KB_DIR_NAME
from reinicorn.corpus import iter_branch_dirs
from reinicorn.doc_types import closable_types
from reinicorn.linter.rules.base import LintRule
from reinicorn.refs import declared_dependency
from reinicorn.staging import STAGE_ACTIVE

if TYPE_CHECKING:
    from pathlib import Path


class DocStructureRule(LintRule):
    def name(self) -> str:
        return f"{KB_DIR_NAME}/plan-structure"

    def run(self, project_root: Path) -> list[str]:
        kb = project_root / KB_DIR_NAME
        if not kb.is_dir():
            return []

        diagnostics: list[str] = []
        for dt in closable_types(project_root):
            doc_name = dt.filename.rsplit("/", 1)[-1]

            for _scope, stage_dir in iter_branch_dirs(kb, dt, STAGE_ACTIVE):
                branch_name = stage_dir.name
                doc_file = stage_dir / doc_name
                rel_doc = doc_file.relative_to(project_root)

                if not doc_file.is_file():
                    diagnostics.append(
                        f"{rel_doc}:1 — Missing {doc_name} in active "
                        f"{dt.key} dir '{branch_name}'."
                    )
                    continue

                content = doc_file.read_text()
                lines = content.splitlines()

                heading_lines = [
                    i + 1 for i, line in enumerate(lines)
                    if line.strip().startswith("##")
                ]
                last_heading = heading_lines[-1] if heading_lines else 1

                for section in dt.required_sections:
                    pattern = (
                        r'(?mi)^\s*##\s+'
                        + re.escape(section).replace(r'\ ', r'\s+')
                    )
                    if not re.search(pattern, content):
                        diagnostics.append(
                            f"{rel_doc}:{last_heading} — Missing "
                            f"'## {section}' section."
                        )

                # Structural presence only. Whether the value resolves to an
                # approved doc is kb/draft-refs' job, and that rule diagnoses
                # a missing field independently so the gate never depends on
                # this rule's severity.
                dep = dt.depends_on
                if dep is not None and declared_dependency(content, dep) is None:
                    diagnostics.append(
                        f"{rel_doc}:1 — Missing '{dep.field}:' frontmatter "
                        f"field (path to the {dep.type} this {dt.key} "
                        "implements, or 'N/A')."
                    )

        return diagnostics
