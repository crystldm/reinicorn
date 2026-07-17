"""Lint rule: validate markdown cross-links."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from reinicorn.config import KB_DIR_NAME
from reinicorn.linter.rules.base import LintRule

if TYPE_CHECKING:
    from pathlib import Path


class CrossLinksRule(LintRule):
    def name(self) -> str:
        return f"{KB_DIR_NAME}/cross-links"

    def run(self, project_root: Path) -> list[str]:
        diagnostics: list[str] = []

        agents = project_root / "AGENTS.md"
        if agents.is_file():
            diagnostics.extend(self._check_file(agents, project_root))

        kb = project_root / KB_DIR_NAME
        if kb.is_dir():
            for md in kb.rglob("*.md"):
                diagnostics.extend(self._check_file(md, project_root))

        return diagnostics

    def _check_file(self, filepath: Path, project_root: Path) -> list[str]:
        rel = filepath.relative_to(project_root)
        diagnostics: list[str] = []
        file_dir = filepath.parent

        in_fence = False
        for line_num, line in enumerate(filepath.read_text().splitlines(), 1):
            # Toggle fenced-code-block state and skip its contents: links inside
            # ``` fences are illustrative examples, not real references.
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue

            for m in re.finditer(r'\[([^\]]*)\]\(([^)]+)\)', line):
                target = m.group(2)

                if re.match(r'^(https?://|mailto:|ftp://|#)', target):
                    continue

                link_path = target.split("#")[0]
                if not link_path:
                    continue

                resolved = file_dir / link_path
                if resolved.exists():
                    continue

                resolved_root = project_root / link_path
                if resolved_root.exists():
                    continue

                diagnostics.append(
                    f"{rel}:{line_num} — Broken link to '{target}'. "
                    f"Target file does not exist."
                )

        return diagnostics
