"""Per-type kb doc reading: show (truncated preview, --full escape hatch) and list."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from reinicorn import console
from reinicorn.config import kb_scope
from reinicorn.doc_types import DRAFTS_DIR_NAME, REGISTRY, drafts_dir
from reinicorn.git import current_branch, repo_root
from reinicorn.kb import branch_dir_name, branch_doc_path, require_kb_dir

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
    dt = REGISTRY[doc_type]
    pattern = re.sub(r"\{\w+\}", "*", dt.filename)
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
    matches = {
        f.stem: f for f in _doc_files(doc_type, repo_dir, include_drafts)
    }
    target = matches.get(slug)
    if target is None:
        console.error(f"no {doc_type} named '{slug}'")
        if matches:
            console.info(f"valid slugs: {', '.join(sorted(matches))}")
        else:
            print(f"{doc_type}s: 0 found")
            console.next_step(REGISTRY[doc_type].create_hint)
        if REGISTRY[doc_type].gated and not include_drafts and any(
            f.stem == slug
            for f in _doc_files(doc_type, repo_dir, include_drafts=True)
        ):
            console.info(f"'{slug}' exists as a draft (not yet approved)")
            console.next_step(f"rcorn {doc_type} show {slug} --include-drafts")
        return 1
    _print_doc(target, doc_type, slug, full)
    return 0


def _title_and_status(path: Path) -> tuple[str, str]:
    """First `# ` heading and `**Status:**` value from the provenance block."""
    title, status = path.stem, ""
    for line in path.read_text().splitlines()[:12]:
        if line.startswith("# ") and title == path.stem:
            title = line[2:].strip()
        elif line.startswith("**Status:**"):
            status = line.removeprefix("**Status:**").strip()
    return title, status


def cmd_doc_list(doc_type: str, include_drafts: bool = False) -> int:
    repo_dir = _repo_dir()
    if repo_dir is None:
        return 1
    files = _doc_files(doc_type, repo_dir, include_drafts)
    if not files:
        print(f"{doc_type}s: 0 found")
        console.next_step(REGISTRY[doc_type].create_hint)
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


def _branch_doc_pattern(doc_type: str) -> str:
    """Glob matching every branch's doc of a branch-addressed type."""
    return REGISTRY[doc_type].filename.replace("{branch}", "*")


def _missing_branch_doc(doc_type: str, branch: str, branches: set[str]) -> int:
    """Recovery hints for a missing branch-addressed doc.

    The create commands only operate on the current branch, so the create
    hint is a dead end for any other branch — list branches that do have
    the doc instead, mirroring the "valid slugs" hint in cmd_doc_show.
    """
    console.error(f"no {doc_type} for branch '{branch}'")
    if branch == current_branch():
        console.next_step(REGISTRY[doc_type].create_hint)
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
    target = branch_doc_path(doc_type, repo_dir, branch)
    if not target.is_file():
        dt = REGISTRY[doc_type]
        branches = {
            f.parent.name
            for f in (repo_dir / dt.dir_path).glob(_branch_doc_pattern(doc_type))
        }
        return _missing_branch_doc(doc_type, branch, branches)
    _print_doc(target, doc_type, branch_dir_name(branch), full)
    return 0


def cmd_plan_show(branch: str | None = None, full: bool = False) -> int:
    return _branch_doc_show("plan", branch, full)


def cmd_retro_show(branch: str | None = None, full: bool = False) -> int:
    repo_dir = _repo_dir()
    if repo_dir is None:
        return 1
    branch = branch or current_branch()
    if not branch:
        console.error("no branch given and none checked out")
        return 1
    active = branch_doc_path("plan", repo_dir, branch).parent / "retro.md"
    target = active if active.is_file() else branch_doc_path("retro", repo_dir, branch)
    if not target.is_file():
        exec_plans = repo_dir / REGISTRY["retro"].dir_path
        active_pattern = str(
            PurePosixPath(_branch_doc_pattern("plan")).with_name("retro.md")
        )
        branches = {
            f.parent.name
            for pattern in (_branch_doc_pattern("retro"), active_pattern)
            for f in exec_plans.glob(pattern)
        }
        return _missing_branch_doc("retro", branch, branches)
    _print_doc(target, "retro", branch_dir_name(branch), full)
    return 0
