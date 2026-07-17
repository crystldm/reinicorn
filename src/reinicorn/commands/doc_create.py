"""Per-type kb doc creation (cmd_spec_create, cmd_prd_create, etc.) and path protection."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from reinicorn import console
from reinicorn.config import KB_DIR_NAME, kb_scope
from reinicorn.doc_types import REGISTRY, drafts_dir, get_doc_dir, get_protected_map
from reinicorn.git import current_branch, repo_root, run_git
from reinicorn.kb import branch_doc_path, commit_kb, require_kb_dir


def _get_author() -> str:
    try:
        return run_git("config", "user.name").stdout.strip()
    except Exception:
        return "unknown"


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower())[:60].rstrip("-")


def _provenance(title: str, author: str, status: str = "draft") -> str:
    return (
        f"# {title}\n"
        f"\n"
        f"**Date:** {date.today().isoformat()}\n"
        f"**Author:** {author}\n"
        f"**Status:** {status}\n"
        f"**Origin:** ai-assisted\n"
        f"**Human-validated:** false\n"
    )


def _typed_dir(doc_type: str, repo_dir: Path) -> Path:
    """Directory a new doc of this type is created in (drafts annex when gated)."""
    if REGISTRY[doc_type].gated:
        return drafts_dir(doc_type, repo_dir)
    return get_doc_dir(doc_type, repo_dir)


def _slug_target(doc_type: str, repo_dir: Path, slug: str) -> Path:
    """Where a new slug-addressed doc lands — filename from the registry, so
    creation can never diverge from how list/show/review resolve the doc.

    Raises FileExistsError when the slot is taken: slug-addressed creates
    never clobber. For gated types the canonical (post-approval) path must be
    vacant too — the review lane treats an occupied final path as "this
    review merged", so drafting over a landed slug would corrupt the lane's
    state.
    """
    fname = REGISTRY[doc_type].filename.format(slug=slug)
    target = _typed_dir(doc_type, repo_dir) / fname
    if target.is_file():
        raise FileExistsError(
            f"'{slug}' already exists at {target} — "
            "edit it, or pick a new title"
        )
    if REGISTRY[doc_type].gated:
        final = get_doc_dir(doc_type, repo_dir) / fname
        if final.is_file():
            raise FileExistsError(
                f"'{slug}' already landed at {final} — approved docs "
                "can't be redrafted under the same slug; pick a new title"
            )
    return target


def _create_spec(repo_dir: Path, title: str, author: str) -> Path:
    slug = _slugify(title)
    target = _slug_target("spec", repo_dir, slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        _provenance(title, author)
        + "\n## Problem\n\n_Describe the problem._\n"
        "\n## Design Goals\n\n_What must be true when this is done._\n"
        "\n## Design\n\n_How it works._\n"
        "\n## Non-Goals\n\n_What this explicitly does not cover._\n"
    )
    return target


def _create_prd(repo_dir: Path, title: str, author: str) -> Path:
    slug = _slugify(title)
    target = _slug_target("prd", repo_dir, slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        _provenance(title, author)
        + "\n## Overview\n\n_One-paragraph summary._\n"
        "\n## User Stories\n\n- As a [role], I want [goal] so that [benefit].\n"
        "\n## Acceptance Criteria\n\n- [ ] _Criterion 1_\n"
        "\n## Out of Scope\n\n_What this PRD explicitly does not cover._\n"
        "\n## Open Questions\n\n_Unresolved decisions._\n"
    )
    return target


def _create_debt(repo_dir: Path, title: str, author: str) -> Path:
    slug = _slugify(title)
    target = _slug_target("debt", repo_dir, slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        _provenance(title, author)
        + "\n**Severity:** medium\n"
        "**Domain:** _domain_\n"
        "**Remediation:** _planned_\n"
        "\n## Impact\n\n_What this debt causes._\n"
        "\n## Remediation Plan\n\n_How to fix it._\n"
    )
    return target


def _create_retro(repo_dir: Path, title: str, author: str) -> Path:
    branch = current_branch() or "unknown"
    # Prefer the active plan dir (retro travels to completed/ at archive time);
    # fall back to the completed path when there is no active plan.
    active_dir = branch_doc_path("plan", repo_dir, branch).parent
    if active_dir.is_dir():
        target = active_dir / Path(REGISTRY["retro"].filename).name
    else:
        target = branch_doc_path("retro", repo_dir, branch)
    target.parent.mkdir(parents=True, exist_ok=True)
    heading = title.strip() if title.strip() else f"Retro: {branch}"
    sections = "".join(
        f"\n## {s}\n\n- \n" for s in REGISTRY["retro"].required_sections
    )
    target.write_text(_provenance(heading, author) + sections)
    return target


def _create_principle(repo_dir: Path, title: str, _author: str) -> Path:
    target = repo_dir / REGISTRY["principle"].filename
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Golden Principles\n\n")

    content = target.read_text()
    existing = re.findall(r'^\d+\.', content, re.MULTILINE)
    num = len(existing) + 1

    target.write_text(
        content.rstrip()
        + f"\n\n{num}. **{title}**\n"
        f"   - _Rule description_\n"
        f"   - Prevents: _What this rule prevents_\n"
    )
    return target


_CREATORS = {
    "spec": _create_spec,
    "prd": _create_prd,
    "debt": _create_debt,
    "retro": _create_retro,
    "principle": _create_principle,
}


def _create_typed(doc_type: str, title: str) -> int:
    """Internal helper used by per-type create entry points."""
    if doc_type not in _CREATORS:
        console.error(f"Unknown doc type '{doc_type}'.")
        return 1

    if REGISTRY[doc_type].title_required and not title.strip():
        console.error("Title is required.")
        return 1

    root = repo_root()
    if root is None:
        return 1
    kb_dir = require_kb_dir(root)

    slug = kb_scope(root)
    repo_dir = kb_dir / slug
    repo_dir.mkdir(parents=True, exist_ok=True)

    author = _get_author()
    creator = _CREATORS[doc_type]
    try:
        filepath = creator(repo_dir, title, author)
    except FileExistsError as e:
        console.error(str(e))
        return 1

    console.success(f"Created: {filepath}")
    # Branch-addressed docs (retros) derive their identity from the branch
    # (encoded in the path), not the title, so the parent dir name is the slug.
    branch_addressed = "{branch}" in REGISTRY[doc_type].filename
    slug = filepath.parent.name if branch_addressed else _slugify(title)
    if REGISTRY[doc_type].gated:
        console.next_step(f"rcorn review start {slug}")
    commit_kb(root, f"doc({doc_type}): {slug}")
    console.next_step("rcorn kb publish")
    return 0


def cmd_spec_create(title: str) -> int:
    return _create_typed("spec", title)


def cmd_prd_create(title: str) -> int:
    return _create_typed("prd", title)


def cmd_debt_create(title: str) -> int:
    return _create_typed("debt", title)


def cmd_retro_create() -> int:
    """Create a retro for the current branch (heading derived from branch)."""
    return _create_typed("retro", "")


def cmd_principle_add(title: str) -> int:
    return _create_typed("principle", title)


def cmd_doc_check_path(file_path: str) -> int:
    """Check if a file path is a protected kb doc path.

    Returns 0 if the path is allowed (not protected, or file already exists).
    Returns 2 if the path is blocked (new file in a protected kb doc dir).
    Prints a message explaining why and how to use the CLI instead.
    """
    path = Path(file_path)

    # Allow edits to existing files
    if path.is_file():
        return 0

    # Only check .md files
    if path.suffix != ".md":
        return 0

    # Check if path is inside a kb repo-scoped doc directory
    # Pattern: .../kb/{repo}/{doc_type_dir}/...
    parts = path.parts
    try:
        kb_idx = parts.index(KB_DIR_NAME)
    except ValueError:
        return 0

    # Need at least {KB_DIR_NAME}/{repo}/{subdir}
    if kb_idx + 2 >= len(parts):
        return 0

    repo_name = parts[kb_idx + 1]
    # Skip shared dirs (., _, generated)
    if repo_name.startswith((".", "_")) or repo_name == "generated":
        return 0

    subdir = parts[kb_idx + 2]

    # Protected doc directories (these map to doc create types)
    protected = get_protected_map()

    # exec-plans are special: plan.md and retro.md are protected
    if subdir == REGISTRY["plan"].dir_path:
        filename = parts[-1]
        plan_filename = REGISTRY["plan"].filename.rsplit("/", 1)[-1]  # "plan.md"
        retro_filename = REGISTRY["retro"].filename.rsplit("/", 1)[-1]  # "retro.md"
        if filename == plan_filename:
            console.error(
                f"Use '{REGISTRY['plan'].create_hint}' instead of "
                "writing kb docs directly."
            )
            return 2
        elif filename == retro_filename:
            console.error(
                f"Use '{REGISTRY['retro'].create_hint}' instead of "
                "writing kb docs directly."
            )
            return 2
        return 0

    if subdir in protected:
        dt = REGISTRY[protected[subdir]]
        console.error(
            f"Use '{dt.create_hint}' instead of writing kb docs directly."
        )
        return 2

    return 0
