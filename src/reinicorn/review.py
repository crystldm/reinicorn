"""Review-lane core: server-side PR refs for gated kb docs.

Pure logic — no console printing (commands/review.py owns UX). The local kb
checkout never leaves main; all ref work happens in a temp clone.

Error contract: remote-facing failures (push, missing origin) raise
RuntimeError with git's stderr in the message so agents can act on them;
local git operations (clone/checkout/commit in temp clones) are exceptional
and may raise subprocess.CalledProcessError.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from reinicorn.doc_types import DRAFTS_DIR_NAME, DocType, drafts_dir, gated_types
from reinicorn.docmeta import (
    FIELD_APPROVED_BY,
    FIELD_REVIEW_PR,
    FIELD_STATUS,
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_IN_REVIEW,
    get_field,
    set_field,
)
from reinicorn.git import file_transport_args, remote_url, run_git, scratch_clone

REVIEW_REF_PREFIX = "review/"


class GatedDraft(NamedTuple):
    """One gated-type draft, read from frontmatter only (no gh/network)."""

    key: str          # doc-type key (e.g. "spec")
    slug: str
    status: str       # frontmatter Status, or "draft" when absent
    review_pr: str    # Review-PR url, or "" when unrecorded


def collect_gated_drafts(scope_dir: Path) -> list[GatedDraft]:
    """All gated-type drafts under one repo-scope dir. Pure local reads."""
    rows: list[GatedDraft] = []
    for dt in gated_types():
        d = drafts_dir(dt.key, scope_dir)
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            text = f.read_text()
            rows.append(GatedDraft(
                dt.key, f.stem,
                get_field(text, FIELD_STATUS) or STATUS_DRAFT,
                get_field(text, FIELD_REVIEW_PR) or "",
            ))
    return rows


@dataclass(frozen=True)
class ReviewTarget:
    doc_type: DocType
    slug: str
    repo_scope: str      # kb repo-scope dir name (e.g. "myrepo")
    draft_path: Path     # absolute path in the local kb working copy
    draft_rel: str       # kb-repo-relative draft path ("myrepo/specs/drafts/x.md")
    final_rel: str       # kb-repo-relative final path ("myrepo/specs/x.md")
    branch: str          # "review/myrepo/spec-x"


def review_branch(repo_scope: str, type_key: str, slug: str) -> str:
    return f"{REVIEW_REF_PREFIX}{repo_scope}/{type_key}-{slug}"


def make_target(
    dt: DocType, repo_scope: str, slug: str, kb_dir: Path,
) -> ReviewTarget:
    """The one place review paths are derived: filename layout (extension
    included) comes from the doc-type registry, not local assumptions."""
    fname = dt.filename.format(slug=slug)
    return ReviewTarget(
        doc_type=dt,
        slug=slug,
        repo_scope=repo_scope,
        draft_path=kb_dir / repo_scope / dt.dir_path / DRAFTS_DIR_NAME / fname,
        draft_rel=f"{repo_scope}/{dt.dir_path}/{DRAFTS_DIR_NAME}/{fname}",
        final_rel=f"{repo_scope}/{dt.dir_path}/{fname}",
        branch=review_branch(repo_scope, dt.key, slug),
    )


def resolve_drafts(
    slug_or_path: str, kb_dir: Path, repo_scope: str,
    type_key: str | None = None,
) -> list[ReviewTarget]:
    """All gated-type drafts matching a slug or file path (0, 1, or many)."""
    p = Path(slug_or_path)
    # Slugs never contain "." (see _slugify in commands/doc_create.py), so the
    # .md-suffix check safely discriminates file paths from bare slugs.
    slug = p.stem if p.suffix == ".md" else slug_or_path
    matches: list[ReviewTarget] = []
    for dt in gated_types():
        if type_key is not None and dt.key != type_key:
            continue
        target = make_target(dt, repo_scope, slug, kb_dir)
        if not target.draft_path.is_file():
            continue
        if p.suffix == ".md" and p.resolve() != target.draft_path.resolve():
            continue
        matches.append(target)
    return matches


def resolve_draft(
    slug_or_path: str, kb_dir: Path, repo_scope: str,
) -> ReviewTarget | None:
    """Single-match convenience: None when missing or ambiguous."""
    matches = resolve_drafts(slug_or_path, kb_dir, repo_scope)
    return matches[0] if len(matches) == 1 else None


def pr_new_url(gh_repo: str, branch: str) -> str:
    return f"https://github.com/{gh_repo}/pull/new/{branch}"


def candidate_text(draft_text: str) -> str:
    """The reviewable candidate: draft content with Status set to in-review."""
    return set_field(draft_text, FIELD_STATUS, STATUS_IN_REVIEW)


def _clone_into(url: str, tmp: str, allow: tuple[str, ...]) -> Path:
    return scratch_clone(
        url, Path(tmp) / "kb-review", transport=allow, depth1=True,
        ident="review",
    )


def push_candidate(kb_dir: Path, target: ReviewTarget) -> None:
    """Create/update the review ref so it differs from main by exactly one
    added file: the candidate at the final path. The draft copy on main is
    untouched, so GitHub's rename detection has nothing to pair (add-only
    PR trick — see the doc-review-lane spec)."""
    url = remote_url(kb_dir)
    if not url:
        raise RuntimeError("kb has no origin remote")
    check = run_git("check-ref-format", "--branch", target.branch,
                    check=False, cwd=kb_dir)
    if check.returncode != 0:
        raise RuntimeError(f"invalid review ref name: {target.branch}")
    allow = file_transport_args(cwd=kb_dir)
    content = candidate_text(target.draft_path.read_text())
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        clone = _clone_into(url, tmp, allow)
        run_git("checkout", "-q", "-B", target.branch, "origin/main", cwd=clone)
        final = clone / target.final_rel
        if final.is_file():
            raise RuntimeError(
                f"'{target.final_rel}' already exists on kb main — slug "
                "collision with a landed doc; recreate the draft under a "
                "new title"
            )
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_text(content)
        run_git("add", "--", target.final_rel, cwd=clone)
        status = run_git("status", "--porcelain", cwd=clone).stdout.strip()
        if status.splitlines() != [f"A  {target.final_rel}"]:
            raise RuntimeError(
                f"review ref would touch more than the candidate file:\n{status}"
            )
        run_git("commit", "-q", "-m",
                f"review({target.doc_type.key}): {target.slug} candidate",
                cwd=clone)
        r = run_git(*allow, "push", "-q", "-f", "origin", target.branch,
                    check=False, cwd=clone)
        if r.returncode != 0:
            raise RuntimeError(f"review ref push failed: {r.stderr.strip()}")


def delete_review_ref(kb_dir: Path, target: ReviewTarget) -> bool:
    """Delete the review ref on origin. Returns False if the push failed."""
    r = run_git(*file_transport_args(cwd=kb_dir), "push", "-q", "origin",
                f":refs/heads/{target.branch}", check=False, cwd=kb_dir)
    return r.returncode == 0


def _remote_show(kb_dir: Path, ref: str, rel: str) -> str | None:
    # fetch→FETCH_HEAD read is not atomic under concurrent reinicorn commands;
    # worst case is a stale read, which is acceptable here.
    r = run_git(*file_transport_args(cwd=kb_dir), "fetch", "-q", "origin", ref,
                check=False, cwd=kb_dir)
    if r.returncode != 0:
        return None
    show = run_git("show", f"FETCH_HEAD:{rel}", check=False, cwd=kb_dir)
    return show.stdout if show.returncode == 0 else None


def candidate_on_ref(kb_dir: Path, target: ReviewTarget) -> str | None:
    return _remote_show(kb_dir, target.branch, target.final_rel)


def remote_main_state(
    kb_dir: Path, target: ReviewTarget,
) -> tuple[str | None, str | None]:
    """(final_text, draft_text) as they exist on origin/main right now.

    One fetch, pure git — part of the no-gh escape hatch. None per file when
    absent (or both None when the fetch fails). The caller decides what the
    combination means: final with Status in-review = merged candidate awaiting
    cleanup; final with another status while the draft is still present =
    slug collision (the final path was occupied by an unrelated doc)."""
    r = run_git(*file_transport_args(cwd=kb_dir), "fetch", "-q", "origin", "main",
                check=False, cwd=kb_dir)
    if r.returncode != 0:
        return None, None

    def show(rel: str) -> str | None:
        s = run_git("show", f"FETCH_HEAD:{rel}", check=False, cwd=kb_dir)
        return s.stdout if s.returncode == 0 else None

    return show(target.final_rel), show(target.draft_rel)


def candidate_matches_draft(kb_dir: Path, target: ReviewTarget) -> bool:
    cand = candidate_on_ref(kb_dir, target)
    if cand is None:
        return False
    return cand == candidate_text(target.draft_path.read_text())


def _finalize_tree(
    clone: Path, target: ReviewTarget, pr_url: str, approved_by: str,
) -> bool:
    """Apply the post-merge finalize to a fresh clone's working tree:
    Status→approved (+ Review-PR / Approved-by stamps), draft removed.
    Returns False when the clone is already fully finalized (no-op).

    The draft is only deleted when the candidate actually landed at the
    final path — finalizing a ref whose merge added nothing there must not
    destroy the (never-reviewed) draft."""
    final = clone / target.final_rel
    if not final.is_file():
        return False  # nothing landed — leave the draft alone
    changed = False
    if get_field(final.read_text(), FIELD_STATUS) != STATUS_APPROVED:
        text = set_field(final.read_text(), FIELD_STATUS, STATUS_APPROVED)
        if pr_url:
            text = set_field(text, FIELD_REVIEW_PR, pr_url)
        if approved_by:
            text = set_field(text, FIELD_APPROVED_BY, approved_by)
        final.write_text(text)
        changed = True
    if (clone / target.draft_rel).is_file():
        run_git("rm", "-q", "--", target.draft_rel, cwd=clone)
        changed = True
    return changed


def cleanup_after_merge(
    kb_dir: Path, target: ReviewTarget, pr_url: str,
    approved_by: str = "", retries: int = 2,
) -> bool:
    """Post-merge finalize on main: Status→approved, stamp Review-PR (+
    Approved-by when known), delete the draft. Shared by `review merge` and
    the CI `_review-cleanup`. Idempotent; pull-rebase-retry via fresh clones
    on push races. Returns True if it changed anything.

    The draft is only deleted when the candidate actually landed at the final
    path — cleanup on a ref whose merge added nothing there must not destroy
    the (never-reviewed) draft."""
    url = remote_url(kb_dir)
    if not url:
        raise RuntimeError("kb has no origin remote")
    allow = file_transport_args(cwd=kb_dir)
    last_stderr = ""
    for _ in range(retries + 1):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            clone = _clone_into(url, tmp, allow)
            if not _finalize_tree(clone, target, pr_url, approved_by):
                return False
            run_git("add", "-A", cwd=clone)
            run_git("commit", "-q", "-m",
                    f"review({target.doc_type.key}): approve {target.slug}, "
                    "remove draft", cwd=clone)
            push = run_git(*allow, "push", "-q", "origin", "HEAD:main",
                           check=False, cwd=clone)
            if push.returncode == 0:
                # Ref gardening: merges reinicorn didn't perform (browser merge
                # + CI cleanup) leave the review branch behind. Best-effort —
                # GitHub's auto-delete may already have removed it.
                delete_review_ref(kb_dir, target)
                return True
            last_stderr = push.stderr.strip()
    raise RuntimeError(
        f"cleanup push kept failing after retries:\n{last_stderr}"
    )
