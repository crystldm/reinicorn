"""Generate a clean kb seed tree for new repos.

Creates the standard kb directory structure with empty templates,
ready to be committed and pushed as the initial kb content.
Derives directory structure from the effective doc-type registry — no hard-coded paths.
Does NOT copy reinicorn's own kb content.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from reinicorn.doc_types import DRAFTS_DIR_NAME, closable_types, registry
from reinicorn.refs import dependency_placeholder
from reinicorn.staging import STAGE_ACTIVE, STAGE_COMPLETED

if TYPE_CHECKING:
    from pathlib import Path

# Structural dirs that aren't doc types but are part of the standard layout.
_STRUCTURAL_DIRS = ("architecture",)
_TEMPLATE_DIR_NAME = "_template"


def generate_seed_tree(root: Path, repo_slug: str) -> None:
    """Create a clean kb template tree at *root*/<repo_slug>/.

    This is used when:
    - Seeding a new bare/empty kb remote
    - Creating a local kb for the first time
    """
    scope = root / repo_slug

    # Create dirs from the registry (unique dir_paths, skip ".")
    seen_dirs: set[str] = set()
    for dt in registry().values():
        if dt.dir_path != "." and dt.dir_path not in seen_dirs:
            seen_dirs.add(dt.dir_path)
            (scope / dt.dir_path).mkdir(parents=True, exist_ok=True)
            (scope / dt.dir_path / ".gitkeep").touch()
            if dt.gated:
                d = scope / dt.dir_path / DRAFTS_DIR_NAME
                d.mkdir(parents=True, exist_ok=True)
                (d / ".gitkeep").touch()

    # Structural dirs not in the registry
    for d in _STRUCTURAL_DIRS:
        (scope / d).mkdir(parents=True, exist_ok=True)
        (scope / d / ".gitkeep").touch()

    # Stage sub-dirs for every closable type (active, completed, _template)
    for dt in closable_types():
        for sub in (STAGE_ACTIVE, STAGE_COMPLETED, _TEMPLATE_DIR_NAME):
            (scope / dt.dir_path / sub).mkdir(parents=True, exist_ok=True)

    # Golden principles (blank template)
    (scope / "golden-principles.md").write_text(
        "# Golden Principles\n\n"
        "> Universal, enforceable rules that keep the codebase legible.\n"
        "> Add principles as the team discovers what matters.\n\n"
        "<!-- No principles defined yet. Add your first one! -->\n"
    )

    # Quality scores
    (scope / "quality-scores.md").write_text(
        "# Quality Scores\n\n"
        "> Track quality metrics for the project.\n\n"
        "<!-- No scores defined yet. -->\n"
    )

    # Scope README is team-owned after creation, so preserve every lexical entry.
    readme = scope / "README.md"
    if not os.path.lexists(readme):
        closable = {dt.key for dt in closable_types()}
        rows = ["| Architecture | `architecture/` |"]
        for dt in registry().values():
            if dt.readme_label is None:
                continue
            if dt.dir_path == ".":
                location = dt.filename
            elif dt.key in closable:
                location = f"{dt.dir_path}/{STAGE_ACTIVE}/"
            else:
                location = f"{dt.dir_path}/"
            rows.append(f"| {dt.readme_label} | `{location}` |")
        rows.append("| Quality scores | `quality-scores.md` |")
        readme.write_text(
            f"# {repo_slug} knowledge base\n\n"
            "This file is the canonical map for humans and agents.\n\n"
            "| Topic | Location |\n|---|---|\n"
            + "\n".join(rows) + "\n\n"
            "Use `rcorn kb sync` before work and `rcorn kb publish` after KB changes.\n"
            "Create protected documents only through their `rcorn <type> create` command.\n"
        )

    # Lifecycle templates — one per closable type, sections from the registry
    for dt in closable_types():
        template = scope / dt.dir_path / _TEMPLATE_DIR_NAME
        doc_name = dt.filename.rsplit("/", 1)[-1]
        sections = "\n\n".join(f"## {s}" for s in dt.required_sections)
        rel = dt.depends_on
        dep_line = (
            f"{rel.field}: '{dependency_placeholder(rel)}'\n"
            if rel is not None else ""
        )
        # Placeholders are substituted by doc_lifecycle at create time.
        # `branch` is a real field, so the orphan sweep reads the exact ref
        # instead of comparing sanitized directory names.
        (template / doc_name).write_text(
            "---\n"
            f"type: {dt.key}\n"
            f"title: '{dt.key.capitalize()}: [Branch Name]'\n"
            "slug: '[Branch Name]'\n"
            "lifecycle: active\n"
            f"status: {dt.create_status}\n"
            "created: [date]\n"
            "author: '[developer or agent]'\n"
            "branch: '[Branch Name]'\n"
            "ticket: '[TICKET-ID or N/A]'\n"
            f"{dep_line}"
            "---\n\n"
            f"# {dt.key.capitalize()}: [Branch Name]\n\n"
            f"{sections}\n"
        )
    # Root .gitignore
    (root / ".gitignore").write_text("# Generated files\ngenerated/\n")
