"""Kb doc creation (cmd_doc_create, the registry-driven entry point) and path protection."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from reinicorn import console, frontmatter
from reinicorn.config import KB_DIR_NAME, kb_scope
from reinicorn.corpus import doc_path
from reinicorn.doc_types import (
    Addressing,
    CreateMode,
    DocType,
    TitleSource,
    closable_types,
    closer_of,
    drafts_dir,
    filename_placeholders,
    filename_regex,
    get_doc_dir,
    get_protected_map,
    registry,
    seq_display_id,
)
from reinicorn.git import current_branch, repo_root, run_git
from reinicorn.kb import (
    branch_dir_name,
    commit_kb,
    require_kb_dir,
)
from reinicorn.staging import STAGE_ACTIVE, closer_target


def _get_author() -> str:
    try:
        return run_git("config", "user.name").stdout.strip()
    except Exception:
        return "unknown"


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower())[:60].rstrip("-")


def _username_segment(author: str) -> str:
    """Path-safe form of the git author name, for filename patterns that
    take a {username} segment (idea's "{username}/{slug}.md")."""
    return re.sub(r"[^a-z0-9-]", "", author.lower().replace(" ", "-"))


def _provenance(
    title: str, author: str, status: str = "draft",
    *, doc_type: str, extra: dict[str, object] | None = None,
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
    if registry()[doc_type].gated:
        return drafts_dir(doc_type, repo_dir)
    return get_doc_dir(doc_type, repo_dir)


def _slug_target(
    doc_type: str, repo_dir: Path, slug: str,
    values: dict[str, object] | None = None,
) -> Path:
    """Where a new slug-addressed doc lands — filename from the registry, so
    creation can never diverge from how list/show/review resolve the doc.

    Raises FileExistsError when the slot is taken: slug-addressed creates
    never clobber. For gated types the canonical (post-approval) path must be
    vacant too — the review lane treats an occupied final path as "this
    review merged", so drafting over a landed slug would corrupt the lane's
    state.
    """
    fname = registry()[doc_type].filename.format(
        **{"slug": slug, **(values or {})}
    )
    target = _typed_dir(doc_type, repo_dir) / fname
    if target.is_file():
        raise FileExistsError(
            f"'{slug}' already exists at {target} — "
            "edit it, or pick a new title"
        )
    if registry()[doc_type].gated:
        final = get_doc_dir(doc_type, repo_dir) / fname
        if final.is_file():
            raise FileExistsError(
                f"'{slug}' already landed at {final} — approved docs "
                "can't be redrafted under the same slug; pick a new title"
            )
    return target


_PLACEHOLDER_ANY = re.compile(r"\{\w+(?::[^}]*)?\}")


def _next_seq(dt: DocType, repo_dir: Path) -> int:
    """max-existing + 1 over the type's dir (and drafts/ when gated, so two
    open drafts never collide), found by matching the pattern's own regex.

    Allocation is not atomic: concurrent creates in two checkouts, or
    deleting the current maximum, can produce a duplicate or reused number.
    Accepted — it cannot break identity or refs (spec §1).
    """
    glob_pattern = _PLACEHOLDER_ANY.sub("*", dt.filename)
    rx = filename_regex(dt.filename)
    dirs = [get_doc_dir(dt.key, repo_dir)]
    if dt.gated:
        dirs.append(drafts_dir(dt.key, repo_dir))
    highest = 0
    for d in dirs:
        if not d.is_dir():
            continue
        for f in d.glob(glob_pattern):
            m = rx.fullmatch(f.relative_to(d).as_posix())
            if m:
                highest = max(highest, int(m.group("seq")))
    return highest + 1


def _seq_values(dt: DocType, repo_dir: Path) -> tuple[dict[str, object], str | None]:
    """({seq: n} filename values, display id) for a {seq} row; ({}, None)
    otherwise."""
    if "seq" not in filename_placeholders(dt):
        return {}, None
    seq = _next_seq(dt, repo_dir)
    return {"seq": seq}, seq_display_id(dt.filename, seq)


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
    """Branch-addressed target. A closer rides in its closee's dir at
    whatever stage the closee currently lives in (graph lookup, not a
    type-name special case)."""
    if dt.closes is not None:
        return closer_target(dt, repo_dir, branch)
    stage = STAGE_ACTIVE if "stage" in filename_placeholders(dt) else None
    return doc_path(repo_dir, dt, branch, stage=stage)


def _append_doc(dt: DocType, repo_dir: Path, title: str, author: str) -> Path:
    """CreateMode.APPEND: add one templated item to the singleton file."""
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
    if dt.create_mode is CreateMode.APPEND:
        return _append_doc(dt, repo_dir, title, author)
    if dt.addressing is Addressing.BRANCH:
        branch = current_branch() or "unknown"
        target = _branch_target(dt, repo_dir, branch)
        target.parent.mkdir(parents=True, exist_ok=True)
        heading = title.strip() or f"{dt.key.capitalize()}: {branch}"
        target.write_text(render_doc(
            dt, heading, author,
            extra={"branch": branch, "slug": branch_dir_name(branch)},
        ))
        return target
    if dt.title_source is TitleSource.FREE_TEXT:
        slug = _slugify(title)
        seq_values, seq_ident = _seq_values(dt, repo_dir)
        target = get_doc_dir(dt.key, repo_dir) / dt.filename.format(
            slug=slug, username=_username_segment(author), **seq_values,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            # Derived slugs collide silently (the user never chose one), so
            # suffix instead of erroring like title-addressed creates do.
            target = target.with_stem(f"{slug}-2")
        heading = title.split("\n")[0][:80]
        extra: dict[str, object] = {"slug": target.stem}
        if seq_ident is not None:
            extra["id"] = seq_ident
        target.write_text(render_doc(
            dt, heading, author,
            extra=extra, body_params={"text": title},
        ))
        return target
    slug = _slugify(title)
    seq_values, seq_ident = _seq_values(dt, repo_dir)
    target = _slug_target(dt.key, repo_dir, slug, seq_values)
    target.parent.mkdir(parents=True, exist_ok=True)
    seq_extra: dict[str, object] | None = (
        {"id": seq_ident} if seq_ident is not None else None
    )
    target.write_text(render_doc(dt, title, author, extra=seq_extra))
    return target


def cmd_doc_create(doc_type: str, title: str = "") -> int:
    """Create a kb doc of any registry type — the one generic entry point."""
    dt = registry().get(doc_type)
    if dt is None:
        console.error(f"Unknown doc type '{doc_type}'.")
        return 1

    if closer_of(dt) is not None:
        console.error(
            f"Use '{dt.create_hint}' instead — {dt.key} creation in "
            "commands/doc_lifecycle.py runs lifecycle logic (templates, "
            "ticket, overlap check) that this generic path would skip."
        )
        return 1

    if dt.title_source is TitleSource.TITLE and not title.strip():
        console.error("Title is required.")
        return 1
    if dt.title_source is TitleSource.FREE_TEXT and not title.strip():
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
    if dt.addressing is Addressing.BRANCH:
        slug = filepath.parent.name
    elif dt.title_source is TitleSource.FREE_TEXT:
        slug = filepath.stem
    else:
        slug = _slugify(title)
    if dt.gated:
        console.next_step(f"rcorn review start {slug}")
    commit_kb(root, f"doc({dt.key}): {slug}", paths=[filepath])
    console.next_step("rcorn kb publish")
    return 0


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

    # Staged dirs are special: only the closable doc and its closer are
    # protected by name; aux files (progress.md, decisions.md) are not.
    staged = {t.dir_path: t for t in closable_types()}
    if subdir in staged:
        filename = parts[-1]
        guarded = {staged[subdir].filename.rsplit("/", 1)[-1]: staged[subdir]}
        closer = closer_of(staged[subdir])
        if closer is not None:
            guarded[closer.filename] = closer
        hit = guarded.get(filename)
        if hit is not None:
            console.error(
                f"Use '{hit.create_hint}' instead of "
                "writing kb docs directly."
            )
            return 2
        return 0

    if subdir in protected:
        dt = registry()[protected[subdir]]
        console.error(
            f"Use '{dt.create_hint}' instead of writing kb docs directly."
        )
        return 2

    return 0
