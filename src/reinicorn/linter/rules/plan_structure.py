"""Lint rule: validate execution plan structure."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from reinicorn.config import KB_DIR_NAME
from reinicorn.doc_types import REGISTRY
from reinicorn.linter.rules.base import LintRule

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

        for repo_dir in sorted(kb.iterdir()):
            if not repo_dir.is_dir() or repo_dir.name.startswith((".", "_")):
                continue
            active_dir = repo_dir / REGISTRY["plan"].dir_path / "active"
            if not active_dir.is_dir():
                continue

            for plan_dir in sorted(active_dir.iterdir()):
                if not plan_dir.is_dir():
                    continue

                branch_name = plan_dir.name
                plan_file = plan_dir / "plan.md"
                prefix = f"{KB_DIR_NAME}/{repo_dir.name}/exec-plans/active/{branch_name}"
                rel_plan = f"{prefix}/plan.md"

                if not plan_file.is_file():
                    diagnostics.append(
                        f"{rel_plan}:1 — Missing plan.md in active exec plan "
                        f"'{branch_name}'."
                    )
                else:
                    content = plan_file.read_text()
                    lines = content.splitlines()

                    heading_lines = [
                        i + 1 for i, line in enumerate(lines)
                        if line.strip().startswith("##")
                    ]
                    last_heading = heading_lines[-1] if heading_lines else 1

                    plan_dt = REGISTRY["plan"]
                    for section in plan_dt.required_sections:
                        pattern = r'(?mi)^\s*##\s+' + re.escape(section).replace(r'\ ', r'\s+')
                        if not re.search(pattern, content):
                            diagnostics.append(
                                f"{rel_plan}:{last_heading} — Missing '## {section}' section."
                            )

        return diagnostics
