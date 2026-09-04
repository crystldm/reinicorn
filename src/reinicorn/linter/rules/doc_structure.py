"""Lint rule ``kb/required-sections``: every doc of every type with a
non-empty ``required_sections`` carries the headers.

Generalizes the old plan-only structure rule (spec: process-as-config §3)
to the docs still being authored. Exempt, by the spec's own non-goal of no
retroactive sections in closed work: docs in a completed stage, docs whose
``lifecycle`` is no longer active, and approved docs of review-gated types
— their structure was the review lane's to judge while they were drafts
(the lane's CI runs this lint), and changing an approved doc means a new
review, not a lint fix. The two structural checks the old rule made stay:
an active closee dir must hold its doc, and a doc with a ``depends_on``
relation must carry the relation field (whether the value resolves is
``kb/draft-refs``' job).

``kb/plan-structure`` remains accepted as a config alias (see
``RULE_ALIASES``): rule names are enablement keys in deployed
``linters/.lint-config.json`` files, and a silent skip is how a renamed
rule dies.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from reinicorn import frontmatter
from reinicorn.config import KB_DIR_NAME
from reinicorn.corpus import Doc, iter_branch_dirs, iter_docs, iter_scope_dirs
from reinicorn.doc_types import closable_types
from reinicorn.linter.rules.base import LintRule
from reinicorn.refs import declared_dependency
from reinicorn.staging import STAGE_ACTIVE, STAGE_COMPLETED, stage_root

if TYPE_CHECKING:
    from pathlib import Path


def missing_sections(content: str, sections: tuple[str, ...]) -> list[str]:
    """The required headers *content* lacks (``## <name>``, case-insensitive,
    flexible whitespace)."""
    missing: list[str] = []
    for section in sections:
        pattern = (
            r'(?mi)^\s*##\s+'
            + re.escape(section).replace(r'\ ', r'\s+')
        )
        if not re.search(pattern, content):
            missing.append(section)
    return missing


def _closed(doc: Doc) -> bool:
    """A doc no longer being authored (see the module docstring)."""
    dt = doc.dt
    if dt is None:
        return True
    lifecycle = doc.meta.get(frontmatter.FIELD_LIFECYCLE)
    if lifecycle is not None and lifecycle != frontmatter.LIFECYCLE_ACTIVE:
        return True
    status = str(doc.meta.get(frontmatter.FIELD_STATUS) or "").strip().lower()
    return dt.gated and status == frontmatter.STATUS_APPROVED


class DocStructureRule(LintRule):
    def name(self) -> str:
        return f"{KB_DIR_NAME}/required-sections"

    def run(self, project_root: Path) -> list[str]:
        kb = project_root / KB_DIR_NAME
        if not kb.is_dir():
            return []

        diagnostics: list[str] = []
        closable = closable_types(project_root)

        # An active closee dir must hold its doc: the dir is the branch's
        # identity, and an empty one is a doc that was never created.
        for dt in closable:
            doc_name = dt.filename.rsplit("/", 1)[-1]
            for _scope, stage_dir in iter_branch_dirs(kb, dt, STAGE_ACTIVE):
                doc_file = stage_dir / doc_name
                if not doc_file.is_file():
                    rel_doc = doc_file.relative_to(project_root)
                    diagnostics.append(
                        f"{rel_doc}:1 — Missing {doc_name} in active "
                        f"{dt.key} dir '{stage_dir.name}'."
                    )

        completed_roots = [
            stage_root(scope_dir, dt, STAGE_COMPLETED)
            for scope_dir in iter_scope_dirs(kb)
            for dt in closable
        ]

        for doc in iter_docs(kb):
            dt = doc.dt
            if dt is None or _closed(doc):
                continue
            if any(doc.path.is_relative_to(r) for r in completed_roots):
                continue
            rel_doc = doc.path.relative_to(project_root)
            content = doc.path.read_text()

            if dt.required_sections:
                lines = content.splitlines()
                heading_lines = [
                    i + 1 for i, line in enumerate(lines)
                    if line.strip().startswith("##")
                ]
                last_heading = heading_lines[-1] if heading_lines else 1
                for section in missing_sections(content, dt.required_sections):
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
