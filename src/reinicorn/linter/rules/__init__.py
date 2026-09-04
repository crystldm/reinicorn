"""Built-in lint rule registry."""

from __future__ import annotations

from reinicorn.config import KB_DIR_NAME
from reinicorn.linter.rules.cross_links import CrossLinksRule
from reinicorn.linter.rules.doc_structure import DocStructureRule
from reinicorn.linter.rules.docs_freshness import DocsFreshnessRule
from reinicorn.linter.rules.draft_refs import DraftRefsRule
from reinicorn.linter.rules.frontmatter import FrontmatterRule

BUILTIN_RULES = {
    f"{KB_DIR_NAME}/cross-links": CrossLinksRule,
    f"{KB_DIR_NAME}/docs-freshness": DocsFreshnessRule,
    # Named for its original plan-only scope; kept for config compat (see
    # the rule module's docstring). It now covers every closable type.
    f"{KB_DIR_NAME}/plan-structure": DocStructureRule,
    f"{KB_DIR_NAME}/draft-refs": DraftRefsRule,
    f"{KB_DIR_NAME}/frontmatter": FrontmatterRule,
}
