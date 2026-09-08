"""Built-in lint rule registry."""

from __future__ import annotations

from reinicorn.config import KB_DIR_NAME
from reinicorn.linter.rules.closer_filled import CloserFilledRule
from reinicorn.linter.rules.cross_links import CrossLinksRule
from reinicorn.linter.rules.doc_structure import DocStructureRule
from reinicorn.linter.rules.docs_freshness import DocsFreshnessRule
from reinicorn.linter.rules.draft_refs import DraftRefsRule
from reinicorn.linter.rules.frontmatter import FrontmatterRule
from reinicorn.linter.rules.lifecycle import LifecycleRule

BUILTIN_RULES = {
    f"{KB_DIR_NAME}/cross-links": CrossLinksRule,
    f"{KB_DIR_NAME}/docs-freshness": DocsFreshnessRule,
    f"{KB_DIR_NAME}/required-sections": DocStructureRule,
    f"{KB_DIR_NAME}/draft-refs": DraftRefsRule,
    f"{KB_DIR_NAME}/closer-filled": CloserFilledRule,
    f"{KB_DIR_NAME}/lifecycle": LifecycleRule,
    f"{KB_DIR_NAME}/frontmatter": FrontmatterRule,
}

# Former names still accepted in ``linters/.lint-config.json``. Rule names
# are enablement keys in deployed configs and the runner ignores
# unconfigured rules, so a rename without an alias is a silent disable.
RULE_ALIASES = {
    f"{KB_DIR_NAME}/plan-structure": f"{KB_DIR_NAME}/required-sections",
}
