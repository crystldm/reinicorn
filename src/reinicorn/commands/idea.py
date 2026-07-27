"""rcorn idea — quick idea capture."""

from __future__ import annotations

import re
from datetime import date

from reinicorn import console, frontmatter
from reinicorn.config import kb_scope
from reinicorn.doc_types import REGISTRY
from reinicorn.git import repo_root, run_git
from reinicorn.kb import commit_kb, require_kb_dir


def cmd_idea(idea_text: str) -> int:
    if not idea_text.strip():
        console.error('Usage: rcorn idea create "your idea here"')
        return 1

    root = repo_root()
    if root is None:
        return 1
    kb_dir = require_kb_dir(root)

    try:
        author = run_git("config", "user.name").stdout.strip()
    except Exception:
        author = "unknown"
    username = re.sub(r"[^a-z0-9-]", "", author.lower().replace(" ", "-"))
    date_today = date.today()

    slug = re.sub(r"[^a-z0-9]+", "-", idea_text.lower())[:60].rstrip("-")

    # Filename comes from the registry pattern ({username}/{slug}.md) so
    # `rcorn idea show <slug>` matches; the capture date lives in frontmatter.
    scope_dir = kb_dir / kb_scope(root)
    filepath = scope_dir / REGISTRY["idea"].dir_path / REGISTRY["idea"].filename.format(
        username=username, slug=slug,
    )
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if filepath.exists():
        filepath = filepath.with_stem(f"{slug}-2")

    title = idea_text.split("\n")[0][:80]

    filepath.write_text(frontmatter.render(
        {
            "type": "idea",
            "title": title,
            "slug": filepath.stem,
            "lifecycle": frontmatter.LIFECYCLE_ACTIVE,
            "status": "new",
            "created": date_today,
            "author": author,
            "origin": frontmatter.ORIGIN_AI,
            "human_validated": False,
        },
        f"\n# {title}\n"
        f"\n## Description\n\n{idea_text}\n"
        f"\n## Notes\n\n_No additional notes yet._\n",
    ))

    console.success(f"Idea captured: {filepath}")

    commit_kb(root, f"idea: {slug}")

    return 0
