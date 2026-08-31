"""Per-type kb doc reading: show (truncated preview, --full escape hatch) and list."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from reinicorn import console, frontmatter
from reinicorn.config import kb_scope
from reinicorn.corpus import doc_path
from reinicorn.doc_types import (
    DRAFTS_DIR_NAME,
    drafts_dir,
    filename_placeholders,
    registry,
)
from reinicorn.git import current_branch, repo_root
from reinicorn.kb import branch_dir_name, require_kb_dir
from reinicorn.staging import STAGE_ACTIVE, STAGES, closer_target

if TYPE_CHECKING:
    from pathlib import Path

PREVIEW_CHARS = 1500


def _repo_dir() -> Path | None:
    root = repo_root()
    if root is None:
        return None
    kb_dir = require_kb_dir(root)
    return kb_dir / kb_scope(root)


def _doc_files(
    doc_type: str, repo_dir: Path, include_drafts: bool = False,
) -> list[Path]:
    """All docs of a slug-addressed type, index files and drafts excluded.

    Default output explicitly drops any file whose parent directory is the
    drafts annex, regardless of glob shape (patterns with a directory
    component, like idea's */*.md, do descend into subdirectories);
    include_drafts adds the annex explicitly for gated types.
    """
    dt = registry()[doc_type]
    pattern = re.sub(r"\{\w+(?::[^}]*)?\}", "*", dt.filename)
    files = sorted((repo_dir / dt.dir_path).glob(pattern))
    if not include_drafts:
        files = [f for f in files if f.parent.name != DRAFTS_DIR_NAME]
    if include_drafts and dt.gated:
        files += sorted(drafts_dir(doc_type, repo_dir).glob(pattern))
    return [f for f in files if f.name != "index.md"]


def _print_doc(target: Path, doc_type: str, ref: str, full: bool) -> None:
    text = target.read_text()
    if full or len(text) <= PREVIEW_CHARS:
        print(text.rstrip())
        return
    print(text[:PREVIEW_CHARS].rstrip())
    print(f"… (truncated, {len(text)} chars total)")
    console.next_step(f"rcorn {doc_type} show {ref} --full")


def cmd_doc_show(
    doc_type: str, slug: str, full: bool = False, include_drafts: bool = False,
) -> int:
    repo_dir = _repo_dir()
    if repo_dir is None:
        return 1
    files = _doc_files(doc_type, repo_dir, include_drafts)
    matches = {f.stem: f for f in files}
    target = matches.get(slug)
    if target is None and "seq" in filename_placeholders(registry()[doc_type]):
        # {seq} rows resolve by the stamped `id` too. Numbering is
        # best-effort-unique (spec §1), so a duplicated id is reported, not
        # silently picked from.
        id_hits = [
            f for f in files if frontmatter.read(f)[0].get("id") == slug
        ]
        if len(id_hits) == 1:
            target = id_hits[0]
        elif len(id_hits) > 1:
            console.error(
                f"id '{slug}' is ambiguous — it matches: "
                + ", ".join(str(f) for f in id_hits)
            )
            return 1
    if target is None:
        console.error(f"no {doc_type} named '{slug}'")
        if matches:
            console.info(f"valid slugs: {', '.join(sorted(matches))}")
        else:
            print(f"{doc_type}s: 0 found")
            console.next_step(registry()[doc_type].create_hint)
        if registry()[doc_type].gated and not include_drafts and any(
            f.stem == slug
            for f in _doc_files(doc_type, repo_dir, include_drafts=True)
        ):
            console.info(f"'{slug}' exists as a draft (not yet approved)")
            console.next_step(f"rcorn {doc_type} show {slug} --include-drafts")
        return 1
    _print_doc(target, doc_type, slug, full)
    return 0


def _title_and_status(path: Path) -> tuple[str, str]:
    """`title` and `status` from frontmatter, falling back to the filename."""
    meta, _ = frontmatter.read(path)
    return (
        str(meta.get("title") or path.stem),
        str(meta.get(frontmatter.FIELD_STATUS) or ""),
    )


def cmd_doc_list(doc_type: str, include_drafts: bool = False) -> int:
    repo_dir = _repo_dir()
    if repo_dir is None:
        return 1
    files = _doc_files(doc_type, repo_dir, include_drafts)
    if not files:
        print(f"{doc_type}s: 0 found")
        console.next_step(registry()[doc_type].create_hint)
        return 0
    print(f"{doc_type}s: {len(files)} total")
    for f in files:
        title, status = _title_and_status(f)
        marker = "[DRAFT] " if f.parent.name == DRAFTS_DIR_NAME else ""
        line = f"{marker}{f.stem} — {title}"
        if status:
            line += f" [{status}]"
        console.info(line)
    console.next_step(f"rcorn {doc_type} show <slug>")
    return 0


def _branch_doc_pattern(doc_type: str, stage: str = STAGE_ACTIVE) -> str:
    """Glob matching every branch's doc of a branch-addressed type."""
    return (
        registry()[doc_type].filename
        .replace("{stage}", stage)
        .replace("{branch}", "*")
    )


def _missing_branch_doc(doc_type: str, branch: str, branches: set[str]) -> int:
    """Recovery hints for a missing branch-addressed doc.

    The create commands only operate on the current branch, so the create
    hint is a dead end for any other branch — list branches that do have
    the doc instead, mirroring the "valid slugs" hint in cmd_doc_show.
    """
    console.error(f"no {doc_type} for branch '{branch}'")
    if branch == current_branch():
        console.next_step(registry()[doc_type].create_hint)
    elif branches:
        console.info(f"branches with a {doc_type}: {', '.join(sorted(branches))}")
    else:
        print(f"{doc_type}s: 0 found")
    return 1


def _branch_doc_show(doc_type: str, branch: str | None, full: bool) -> int:
    repo_dir = _repo_dir()
    if repo_dir is None:
        return 1
    branch = branch or current_branch()
    if not branch:
        console.error("no branch given and none checked out")
        return 1
    dt = registry()[doc_type]
    stage = STAGE_ACTIVE if "stage" in filename_placeholders(dt) else None
    target = doc_path(repo_dir, dt, branch, stage=stage)
    if not target.is_file():
        branches = {
            f.parent.name
            for f in (repo_dir / dt.dir_path).glob(_branch_doc_pattern(doc_type))
        }
        return _missing_branch_doc(doc_type, branch, branches)
    _print_doc(target, doc_type, branch_dir_name(branch), full)
    return 0


def cmd_branch_show(
    doc_type: str, branch: str | None = None, full: bool = False,
) -> int:
    """Show a branch-addressed doc. A closer rides in its closee's dir at
    whatever stage the closee currently lives in (graph lookup, not a
    type-name special case)."""
    dt = registry()[doc_type]
    if dt.closes is None:
        return _branch_doc_show(doc_type, branch, full)
    repo_dir = _repo_dir()
    if repo_dir is None:
        return 1
    branch = branch or current_branch()
    if not branch:
        console.error("no branch given and none checked out")
        return 1
    target = closer_target(dt, repo_dir, branch)
    if not target.is_file():
        closee = registry()[dt.closes.type]
        branches = {
            f.parent.name
            for stage in STAGES
            for f in (repo_dir / closee.dir_path).glob(
                str(
                    PurePosixPath(
                        _branch_doc_pattern(closee.key, stage)
                    ).with_name(dt.filename)
                )
            )
        }
        return _missing_branch_doc(doc_type, branch, branches)
    _print_doc(target, doc_type, branch_dir_name(branch), full)
    return 0
