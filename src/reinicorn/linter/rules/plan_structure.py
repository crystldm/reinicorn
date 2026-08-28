"""Lint rule: validate execution plan structure."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from reinicorn.config import KB_DIR_NAME
from reinicorn.corpus import iter_branch_dirs
from reinicorn.doc_types import registry
from reinicorn.frontmatter import FIELD_SPEC
from reinicorn.linter.rules.base import LintRule
from reinicorn.linter.spec_refs import declared_spec

if TYPE_CHECKING:
    from pathlib import Path


class PlanStructureRule(LintRule):
    def name(self) -> str:
        return f"{KB_DIR_NAME}/plan-structure"

    def run(self, project_root: Path) -> list[str]:
        kb = project_root / KB_DIR_NAME
        if not kb.is_dir():
            return []

        diagnostics: list[str] = []
        plan_dt = registry(project_root).get("plan")
        if plan_dt is None:
            return []
        doc_name = plan_dt.filename.rsplit("/", 1)[-1]

        for _scope, plan_dir in iter_branch_dirs(kb, plan_dt):
            branch_name = plan_dir.name
            plan_file = plan_dir / doc_name
            rel_plan = plan_file.relative_to(project_root)

            if not plan_file.is_file():
                diagnostics.append(
                    f"{rel_plan}:1 — Missing {doc_name} in active exec plan "
                    f"'{branch_name}'."
                )
                continue

            content = plan_file.read_text()
            lines = content.splitlines()

            heading_lines = [
                i + 1 for i, line in enumerate(lines)
                if line.strip().startswith("##")
            ]
            last_heading = heading_lines[-1] if heading_lines else 1

            for section in plan_dt.required_sections:
                pattern = r'(?mi)^\s*##\s+' + re.escape(section).replace(r'\ ', r'\s+')
                if not re.search(pattern, content):
                    diagnostics.append(
                        f"{rel_plan}:{last_heading} — Missing '## {section}' section."
                    )

            # Structural presence only. Whether the value resolves to an
            # approved doc is kb/draft-refs' job, and that rule diagnoses
            # a missing field independently so the gate never depends on
            # this rule's severity.
            if declared_spec(content) is None:
                diagnostics.append(
                    f"{rel_plan}:1 — Missing '{FIELD_SPEC}:' frontmatter field "
                    "(path to the spec this plan implements, or 'N/A')."
                )

        return diagnostics
