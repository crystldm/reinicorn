"""Built-in lint rule registry."""

from __future__ import annotations

from reinicorn.config import KB_DIR_NAME
from reinicorn.linter.rules.cross_links import CrossLinksRule
from reinicorn.linter.rules.docs_freshness import DocsFreshnessRule
from reinicorn.linter.rules.draft_refs import DraftRefsRule
from reinicorn.linter.rules.plan_structure import PlanStructureRule

BUILTIN_RULES = {
    f"{KB_DIR_NAME}/cross-links": CrossLinksRule,
    f"{KB_DIR_NAME}/docs-freshness": DocsFreshnessRule,
    f"{KB_DIR_NAME}/plan-structure": PlanStructureRule,
    f"{KB_DIR_NAME}/draft-refs": DraftRefsRule,
}
