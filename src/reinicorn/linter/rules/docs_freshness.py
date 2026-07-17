"""Lint rule: check kb document freshness."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from reinicorn.config import KB_DIR_NAME
from reinicorn.doc_types import REGISTRY
from reinicorn.linter.rules.base import LintRule

if TYPE_CHECKING:
    from pathlib import Path


def _key_docs(project_root: Path) -> list[str]:
    """Build KEY_DOCS list dynamically based on repo-scoped kb dirs."""
    kb = project_root / KB_DIR_NAME
    if not kb.is_dir():
        return ["AGENTS.md"]

    docs = ["AGENTS.md"]
    for repo_dir in sorted(kb.iterdir()):
        if not repo_dir.is_dir() or repo_dir.name.startswith((".", "_")):
            continue
        prefix = f"{KB_DIR_NAME}/{repo_dir.name}"
        docs.extend([
            f"{prefix}/architecture/ARCHITECTURE.md",
            f"{prefix}/architecture/dependency-rules.md",
            f"{prefix}/golden-principles.md",
            f"{prefix}/quality-scores.md",
        ])
        for dt in REGISTRY.values():
            if dt.index_file:
                docs.append(f"{prefix}/{dt.dir_path}/{dt.index_file}")
        design_md = repo_dir / "DESIGN.md"
        if design_md.is_file():
            docs.append(f"{prefix}/DESIGN.md")

    return docs


class DocsFreshnessRule(LintRule):
    def __init__(self, max_days: int = 30) -> None:
        self._max_days = max_days

    def name(self) -> str:
        return f"{KB_DIR_NAME}/docs-freshness"

    def run(self, project_root: Path) -> list[str]:
        diagnostics: list[str] = []
        now = time.time()
        threshold = self._max_days * 86400

        for doc_rel in _key_docs(project_root):
            full_path = project_root / doc_rel
            if not full_path.is_file():
                continue

            mod_time = full_path.stat().st_mtime
            age = now - mod_time
            days_old = int(age / 86400)

            if age > threshold:
                diagnostics.append(
                    f"{doc_rel}:1 — Document is {days_old} days stale "
                    f"(threshold: {self._max_days} days)."
                )

        return diagnostics
