"""Per-type kb doc creation (cmd_spec_create, cmd_prd_create, etc.) and path protection."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from reinicorn import console, frontmatter
from reinicorn.config import KB_DIR_NAME, kb_scope
from reinicorn.doc_types import (
    REGISTRY,
    DocType,
    drafts_dir,
    get_doc_dir,
    get_protected_map,
)
from reinicorn.git import current_branch, repo_root, run_git
from reinicorn.kb import (
    branch_dir_name,
    branch_doc_path,
    commit_kb,
    require_kb_dir,
)


def _get_author() -> str:
    try:
        return run_git("config", "user.name").stdout.strip()
    except Exception:
        return "unknown"


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower())[:60].rstrip("-")


def _provenance(
    title: str, author: str, status: str = "draft",
    doc_type: str = "spec", *, extra: dict[str, object] | None = None,
) -> str:
    """Frontmatter block plus the `# title` H1 that opens every doc body.

    frontmatter.render validates on the way out, so this path and the
    `kb/frontmatter` lint rule share one definition of valid.
    """
    meta: dict[str, object] = {
        "type": doc_type,
        "title": title,
        "slug": _slugify(title),
        "lifecycle": frontmatter.LIFECYCLE_ACTIVE,
        "status": status,
        "created": date.today(),
        "author": author,
        "origin": frontmatter.ORIGIN_AI,
        "human_validated": False,
    }
    meta.update(extra or {})
    return frontmatter.render(meta, f"\n# {title}\n")


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


def render_doc(
    dt: DocType, title: str, author: str, *,
    extra: dict[str, object] | None = None,
    body_params: dict[str, str] | None = None,
) -> str:
    """Frontmatter + H1 + the type's template body — the one rendering path
    every doc-type creation goes through (registry-driven-doc-types stage 1)."""
    sections = "".join(f"\n## {s}\n\n- \n" for s in dt.required_sections)
    params: dict[str, str] = {
        "title": title, "author": author,
        "date": date.today().isoformat(), "sections": sections,
    }
    params.update(body_params or {})
    merged: dict[str, object] = dict(dt.extra_meta)
    merged.update(extra or {})
    return _provenance(
        title, author, status=dt.create_status, doc_type=dt.key, extra=merged,
    ) + dt.template_body.format(**params)


def _branch_target(dt: DocType, repo_dir: Path, branch: str) -> Path:
    """Branch-addressed target. Retro rides with an active plan when one
    exists (spec non-goal: this coupling stays code; identity check against
    the registry row keeps type knowledge out of string comparisons)."""
    if dt is REGISTRY["retro"]:
        active_dir = branch_doc_path("plan", repo_dir, branch).parent
        if active_dir.is_dir():
            return active_dir / Path(dt.filename).name
    return branch_doc_path(dt.key, repo_dir, branch)


def _append_doc(dt: DocType, repo_dir: Path, title: str, author: str) -> Path:
    """create_mode="append": add one templated item to the singleton file."""
    target = repo_dir / dt.filename
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_provenance(
            "Golden Principles", author or "unknown",
            status=dt.create_status, doc_type=dt.key,
            extra={"slug": target.stem},
        ) + "\n")
    content = target.read_text()
    num = len(re.findall(r"^\d+\.", content, re.MULTILINE)) + 1
    target.write_text(
        content.rstrip() + dt.template_body.format(num=num, title=title)
    )
    return target


def _create_doc(dt: DocType, repo_dir: Path, title: str, author: str) -> Path:
    """Create (or append) one doc from its registry row."""
    if dt.create_mode == "append":
        return _append_doc(dt, repo_dir, title, author)
    if dt.addressing == "branch":
        branch = current_branch() or "unknown"
        target = _branch_target(dt, repo_dir, branch)
        target.parent.mkdir(parents=True, exist_ok=True)
        heading = title.strip() or f"{dt.key.capitalize()}: {branch}"
        target.write_text(render_doc(
            dt, heading, author,
            extra={"branch": branch, "slug": branch_dir_name(branch)},
        ))
        return target
    if dt.title_source == "free_text":
        username = re.sub(r"[^a-z0-9-]", "", author.lower().replace(" ", "-"))
        slug = _slugify(title)
        target = get_doc_dir(dt.key, repo_dir) / dt.filename.format(
            slug=slug, username=username,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            # Derived slugs collide silently (the user never chose one), so
            # suffix instead of erroring like title-addressed creates do.
            target = target.with_stem(f"{slug}-2")
        heading = title.split("\n")[0][:80]
        target.write_text(render_doc(
            dt, heading, author,
            extra={"slug": target.stem}, body_params={"text": title},
        ))
        return target
    slug = _slugify(title)
    target = _slug_target(dt.key, repo_dir, slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_doc(dt, title, author))
    return target


def cmd_doc_create(doc_type: str, title: str = "") -> int:
    """Create a kb doc of any registry type — the one generic entry point."""
    dt = REGISTRY.get(doc_type)
    if dt is None:
        console.error(f"Unknown doc type '{doc_type}'.")
        return 1

    if dt.title_source == "title" and not title.strip():
        console.error("Title is required.")
        return 1
    if dt.title_source == "free_text" and not title.strip():
        console.error(
            f'Usage: rcorn {dt.key} {dt.create_verb} "your {dt.key} here"'
        )
        return 1

    root = repo_root()
    if root is None:
        return 1
    kb_dir = require_kb_dir(root)

    repo_dir = kb_dir / kb_scope(root)
    repo_dir.mkdir(parents=True, exist_ok=True)

    author = _get_author()
    try:
        filepath = _create_doc(dt, repo_dir, title, author)
    except FileExistsError as e:
        console.error(str(e))
        return 1

    console.success(f"Created: {filepath}")
    # Branch-addressed docs derive identity from the branch (encoded in the
    # path); free-text docs from the deduped filename; the rest from the title.
    if dt.addressing == "branch":
        slug = filepath.parent.name
    elif dt.title_source == "free_text":
        slug = filepath.stem
    else:
        slug = _slugify(title)
    if dt.gated:
        console.next_step(f"rcorn review start {slug}")
    commit_kb(root, f"doc({dt.key}): {slug}", paths=[filepath])
    console.next_step("rcorn kb publish")
    return 0


def cmd_spec_create(title: str) -> int:
    return cmd_doc_create("spec", title)


def cmd_prd_create(title: str) -> int:
    return cmd_doc_create("prd", title)


def cmd_debt_create(title: str) -> int:
    return cmd_doc_create("debt", title)


def cmd_retro_create() -> int:
    return cmd_doc_create("retro", "")


def cmd_principle_add(title: str) -> int:
    return cmd_doc_create("principle", title)


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
