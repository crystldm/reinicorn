"""Centralized doc-type registry.

Single source of truth for all kb document type metadata: paths,
filename patterns, protection flags, linter sections, and index files.

NOTE: This registry is internal Python code. A future enhancement could
allow per-repo custom doc types via a config file (e.g. doc-types.yaml
in the kb), but that is out of scope for now.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class DocType:
    """Metadata for a single kb document type."""

    key: str
    dir_path: str  # Relative to repo-scoped dir (e.g. "specs")
    filename: str  # Pattern: "{slug}.md", "active/{branch}/plan.md", etc.
    protected: bool  # Whether direct kb edits are blocked
    create_hint: str  # Exact CLI command that creates docs of this type
    title_required: bool = True  # Whether create requires a title argument
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
        required_sections=("Goal", "Acceptance Criteria", "Tasks"),
    ),
    "prd": DocType(
        key="prd",
        dir_path="prds",
        filename="{slug}.md",
        protected=True,
        create_hint='rcorn prd create "<title>"',
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
        index_file="index.md",
        required_sections=("Impact", "Remediation Plan"),
    ),
    "idea": DocType(
        key="idea",
        dir_path="ideas",
        filename="{username}/{slug}.md",
        protected=True,
        create_hint='rcorn idea create "<idea>"',
    ),
    "retro": DocType(
        key="retro",
        dir_path="exec-plans",
        filename="completed/{branch}/retro.md",
        protected=True,
        create_hint="rcorn retro create",
        title_required=False,
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
    ),
}


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
