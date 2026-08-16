"""Centralized doc-type registry.

Single source of truth for all kb document type metadata: paths,
filename patterns, protection flags, linter sections, and index files.

NOTE: This registry is internal Python code. A future enhancement could
allow per-repo custom doc types via a config file (e.g. doc-types.yaml
in the kb), but that is out of scope for now.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class Addressing(Enum):
    """How a doc of this type is identified and pathed."""

    SLUG = "slug"
    BRANCH = "branch"
    SINGLETON = "singleton"


class TitleSource(Enum):
    """Where a new doc's title comes from at creation time."""

    TITLE = "title"
    FREE_TEXT = "free_text"
    NONE = "none"


class CreateMode(Enum):
    """Whether creation writes a new file or appends to the singleton."""

    FILE = "file"
    APPEND = "append"


@dataclass(frozen=True)
class DocType:
    """Metadata for a single kb document type."""

    key: str
    dir_path: str  # Relative to repo-scoped dir (e.g. "specs")
    filename: str  # Pattern: "{slug}.md", "active/{branch}/plan.md", etc.
    protected: bool  # Whether direct kb edits are blocked
    create_hint: str  # Exact CLI command that creates docs of this type
    help_text: str  # CLI group help (hand-written in cli.py until stage 2)
    # Creation body appended after the frontmatter + H1. File-mode bodies may
    # name {title} {author} {date} {sections} {text}; append-mode bodies
    # (CreateMode.APPEND) are formatted with {num} and {title} only.
    template_body: str
    addressing: Addressing
    title_source: TitleSource = TitleSource.TITLE
    create_verb: str = "create"
    create_mode: CreateMode = CreateMode.FILE
    create_status: str = "draft"  # frontmatter `status:` a new doc opens with
    # Static per-type frontmatter, as (key, value) pairs (frozen-friendly).
    extra_meta: tuple[tuple[str, str], ...] = ()
    readme_label: str | None = None  # Seeded kb README row; None = no row
    index_file: str | None = None  # For freshness linter
    required_sections: tuple[str, ...] = ()  # Linter checks these headers
    gated: bool = False  # Review-gated: create writes to drafts/, approval via the review lane


REGISTRY: dict[str, DocType] = {
    "spec": DocType(
        key="spec",
        dir_path="specs",
        filename="{slug}.md",
        protected=True,
        create_hint='rcorn spec create "<title>"',
        help_text="Spec doc operations (the implementation contract)",
        template_body=(
            "\n## Problem\n\n_Describe the problem._\n"
            "\n## Design Goals\n\n_What must be true when this is done._\n"
            "\n## Design\n\n_How it works._\n"
            "\n## Non-Goals\n\n_What this explicitly does not cover._\n"
        ),
        addressing=Addressing.SLUG,
        readme_label="Approved specs",
        index_file="index.md",
        required_sections=("Problem", "Design Goals", "Design", "Non-Goals"),
        gated=True,
    ),
    "plan": DocType(
        key="plan",
        dir_path="exec-plans",
        filename="active/{branch}/plan.md",
        protected=True,
        create_hint="rcorn plan create",
        help_text="Execution plan operations",
        template_body="",  # fallback plan.md is frontmatter + H1 only
        addressing=Addressing.BRANCH,
        title_source=TitleSource.NONE,
        create_status="planning",
        readme_label="Active plans",
        required_sections=("Goal", "Acceptance Criteria", "Tasks"),
    ),
    "prd": DocType(
        key="prd",
        dir_path="prds",
        filename="{slug}.md",
        protected=True,
        create_hint='rcorn prd create "<title>"',
        help_text="Product requirements doc operations",
        template_body=(
            "\n## Overview\n\n_One-paragraph summary._\n"
            "\n## User Stories\n\n- As a [role], I want [goal] so that [benefit].\n"
            "\n## Acceptance Criteria\n\n- [ ] _Criterion 1_\n"
            "\n## Out of Scope\n\n_What this PRD explicitly does not cover._\n"
            "\n## Open Questions\n\n_Unresolved decisions._\n"
        ),
        addressing=Addressing.SLUG,
        readme_label="Product requirements",
        index_file="index.md",
        required_sections=(
            "Overview",
            "User Stories",
            "Acceptance Criteria",
            "Out of Scope",
            "Open Questions",
        ),
    ),
    "debt": DocType(
        key="debt",
        dir_path="tech-debt",
        filename="{slug}.md",
        protected=True,
        create_hint='rcorn debt create "<title>"',
        help_text="Tech debt doc operations",
        template_body=(
            "\n## Impact\n\n_What this debt causes._\n"
            "\n## Remediation Plan\n\n_How to fix it._\n"
        ),
        addressing=Addressing.SLUG,
        extra_meta=(
            ("severity", "medium"),
            ("category", "_domain_"),
            ("remediation", "planned"),
        ),
        readme_label="Technical debt",
        index_file="index.md",
        required_sections=("Impact", "Remediation Plan"),
    ),
    "idea": DocType(
        key="idea",
        dir_path="ideas",
        filename="{username}/{slug}.md",
        protected=True,
        create_hint='rcorn idea create "<idea>"',
        help_text="Idea capture",
        template_body=(
            "\n## Description\n\n{text}\n"
            "\n## Notes\n\n_No additional notes yet._\n"
        ),
        addressing=Addressing.SLUG,
        title_source=TitleSource.FREE_TEXT,
        create_status="new",
    ),
    "retro": DocType(
        key="retro",
        dir_path="exec-plans",
        filename="completed/{branch}/retro.md",
        protected=True,
        create_hint="rcorn retro create",
        help_text="Retrospective operations",
        template_body="{sections}",
        addressing=Addressing.BRANCH,
        title_source=TitleSource.NONE,
        required_sections=(
            "What Went Well",
            "What Could Be Improved",
            "Lessons Learned",
            "Action Items",
        ),
    ),
    "principle": DocType(
        key="principle",
        dir_path=".",
        filename="golden-principles.md",
        protected=False,
        create_hint='rcorn principle add "<title>"',
        help_text="Golden principle operations",
        template_body=(
            "\n\n{num}. **{title}**\n"
            "   - _Rule description_\n"
            "   - Prevents: _What this rule prevents_\n"
        ),
        addressing=Addressing.SINGLETON,
        create_verb="add",
        create_mode=CreateMode.APPEND,
        create_status="active",
        readme_label="Golden principles",
    ),
}


def _validate_registry() -> None:
    """Load-time invariants over REGISTRY rows.

    A plain raise, not `assert`: it must fire under `python -O` too, so an
    invalid row can never load (spec: registry-driven-doc-types).
    """
    for dt in REGISTRY.values():
        if dt.gated and dt.addressing is not Addressing.SLUG:
            raise ValueError(
                f"doc_types.REGISTRY['{dt.key}']: gated=True requires "
                f"Addressing.SLUG, got {dt.addressing} — the review lane "
                "derives candidate paths from slugs (review.make_target). "
                "Fix the row in src/reinicorn/doc_types.py."
            )


_validate_registry()


def get_doc_dir(key: str, repo_dir: Path) -> Path:
    """Resolve the full directory path for a doc type within a repo scope dir."""
    return repo_dir / REGISTRY[key].dir_path


def get_protected_map() -> dict[str, str]:
    """Return {dir_path: key} for all protected doc types.

    Excludes entries with dir_path "." (like principle) since they live
    at the repo-scope root and don't have a distinct subdirectory.
    """
    return {
        dt.dir_path: dt.key
        for dt in REGISTRY.values()
        if dt.protected and dt.dir_path != "."
    }


def by_dir(dir_name: str) -> DocType | None:
    """Reverse lookup: find a DocType by its directory name."""
    for dt in REGISTRY.values():
        if dt.dir_path == dir_name:
            return dt
    return None


DRAFTS_DIR_NAME = "drafts"


def drafts_dir(key: str, repo_dir: Path) -> Path:
    """Drafts annex for a gated doc type within a repo scope dir."""
    return repo_dir / REGISTRY[key].dir_path / DRAFTS_DIR_NAME


def gated_types() -> list[DocType]:
    """All review-gated doc types (drafts lifecycle applies)."""
    return [dt for dt in REGISTRY.values() if dt.gated]
