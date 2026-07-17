"""Generate a clean kb seed tree for new repos.

Creates the standard kb directory structure with empty templates,
ready to be committed and pushed as the initial kb content.
Derives directory structure from the doc_types REGISTRY — no hard-coded paths.
Does NOT copy reinicorn's own kb content.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from reinicorn.doc_types import DRAFTS_DIR_NAME, REGISTRY

if TYPE_CHECKING:
    from pathlib import Path

# Structural dirs that aren't doc types but are part of the standard layout.
_STRUCTURAL_DIRS = ("architecture",)


def generate_seed_tree(root: Path, repo_slug: str) -> None:
    """Create a clean kb template tree at *root*/<repo_slug>/.

    This is used when:
    - Seeding a new bare/empty kb remote
    - Creating a local kb for the first time
    """
    scope = root / repo_slug

    # Create dirs from the registry (unique dir_paths, skip ".")
    seen_dirs: set[str] = set()
    for dt in REGISTRY.values():
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

    # Exec-plan sub-dirs (active, completed, _template)
    plan_dir = REGISTRY["plan"].dir_path
    for sub in ("active", "completed", "_template"):
        (scope / plan_dir / sub).mkdir(parents=True, exist_ok=True)

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
        readme.write_text(
            f"# {repo_slug} knowledge base\n\n"
            "This file is the canonical map for humans and agents.\n\n"
            "| Topic | Location |\n|---|---|\n"
            "| Golden principles | `golden-principles.md` |\n"
            "| Architecture | `architecture/` |\n"
            f"| Approved specs | `{REGISTRY['spec'].dir_path}/` |\n"
            f"| Product requirements | `{REGISTRY['prd'].dir_path}/` |\n"
            f"| Active plans | `{plan_dir}/active/` |\n"
            "| Quality scores | `quality-scores.md` |\n"
            f"| Technical debt | `{REGISTRY['debt'].dir_path}/` |\n\n"
            "Use `rcorn kb sync` before work and `rcorn kb publish` after KB changes.\n"
            "Create protected documents only through their `rcorn <type> create` command.\n"
        )

    # Exec plan template — sections from the registry
    template = scope / plan_dir / "_template"
    plan_dt = REGISTRY["plan"]
    sections = "\n\n".join(f"## {s}" for s in plan_dt.required_sections)
    (template / "plan.md").write_text(
        "# Execution Plan: [Branch Name]\n\n"
        "**Author:** [developer or agent]\n"
        "**Date:** [date]\n"
        "**Status:** planning\n\n"
        f"{sections}\n"
    )
    # Root .gitignore
    (root / ".gitignore").write_text("# Generated files\ngenerated/\n")
