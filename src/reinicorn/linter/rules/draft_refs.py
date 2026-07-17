"""Lint rule: active plans must not build on unapproved (draft/in-review) docs."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from reinicorn.config import KB_DIR_NAME
from reinicorn.doc_types import DRAFTS_DIR_NAME, REGISTRY
from reinicorn.docmeta import FIELD_STATUS, STATUS_IN_REVIEW, get_field
from reinicorn.linter.rules.base import LintRule

if TYPE_CHECKING:
    from pathlib import Path

# Lookbehind keeps lookalike dirs ("notkb/...") from matching on their tail.
_KB_PATH_RE = re.compile(rf"(?<![\w/]){KB_DIR_NAME}/[\w./-]+\.md")


class DraftRefsRule(LintRule):
    def name(self) -> str:
        return f"{KB_DIR_NAME}/draft-refs"

    def run(self, project_root: Path) -> list[str]:
        diagnostics: list[str] = []
        kb = project_root / KB_DIR_NAME
        if not kb.is_dir():
            return diagnostics

        active_glob = f"*/{REGISTRY['plan'].dir_path}/active/*/plan.md"
        for plan in sorted(kb.glob(active_glob)):
            rel = plan.relative_to(project_root)

            in_fence = False
            for n, line in enumerate(plan.read_text().splitlines(), 1):
                # Fenced code blocks hold illustrative example paths, not real
                # references — mirror cross_links' fence-skipping to avoid
                # false positives on plans that quote example doc paths.
                if line.lstrip().startswith("```"):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue

                for ref in _KB_PATH_RE.findall(line):
                    if f"/{DRAFTS_DIR_NAME}/" in ref:
                        diagnostics.append(
                            f"{rel}:{n} — references drafts-annex doc '{ref}' "
                            "(unapproved; building on a draft needs explicit sign-off)"
                        )
                        continue
                    target = project_root / ref
                    if target.is_file() and \
                            get_field(target.read_text(), FIELD_STATUS) == STATUS_IN_REVIEW:
                        diagnostics.append(
                            f"{rel}:{n} — references in-review doc '{ref}' "
                            "(approval pending)"
                        )

        return diagnostics
