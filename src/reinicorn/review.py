"""Review-lane core: server-side PR refs for gated kb docs.

Pure logic — no console printing (commands/review.py owns UX). The local kb
checkout never leaves main; all ref work happens in a temp clone.

Error contract: remote-facing failures (push, missing origin) raise
RuntimeError whose message comes from `git.explain_failure` — so it always
carries git's own words — and agents can act on them; local git operations
(clone/checkout/commit in temp clones) are exceptional and may raise
subprocess.CalledProcessError (in practice its GitError subclass).
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from reinicorn.doc_types import DRAFTS_DIR_NAME, REGISTRY, DocType, drafts_dir, gated_types
from reinicorn.frontmatter import (
    FIELD_APPROVED_BY,
    FIELD_REVIEW_PR,
    FIELD_STATUS,
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_IN_REVIEW,
    get,
    set_meta,
)
from reinicorn.git import (
    GitFailure,
    explain_failure,
    file_transport_args,
    remote_url,
    run_git,
    scratch_clone,
)

REVIEW_REF_PREFIX = "review/"

_REF_RE = re.compile(
    rf"^{re.escape(REVIEW_REF_PREFIX)}(?P<scope>[^/]+)/(?P<type>[a-z]+)-(?P<slug>[a-z0-9-]+)$"
)


class ReviewRef(NamedTuple):
    """The three parts of a lane ref `review/<scope>/<type>-<slug>`."""

    repo_scope: str
    doc_type: DocType
    slug: str


def parse_review_ref(ref: str) -> ReviewRef | None:
    """Parse a branch name as a lane ref; None for anything else (including
    a `review/` branch whose type is not a registered doc type). The one
    parser every CI entry point shares, so the ref grammar has one home."""
    m = _REF_RE.match(ref)
    if m is None or m.group("type") not in REGISTRY:
        return None
    return ReviewRef(m.group("scope"), REGISTRY[m.group("type")], m.group("slug"))


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
                get(text, FIELD_STATUS) or STATUS_DRAFT,
                get(text, FIELD_REVIEW_PR) or "",
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
    return set_meta(draft_text, {FIELD_STATUS: STATUS_IN_REVIEW})


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
            raise RuntimeError("\n".join(explain_failure(
                f"push the review ref '{target.branch}'", r,
            )))


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


def candidate_matches(candidate: str, draft: str) -> bool:
    """Does a candidate text equal what `review push` would derive from this
    draft? Pure text — shared by the merge-time guard and the CI check."""
    return candidate == candidate_text(draft)


def candidate_matches_draft(kb_dir: Path, target: ReviewTarget) -> bool:
    cand = candidate_on_ref(kb_dir, target)
    if cand is None:
        return False
    return candidate_matches(cand, target.draft_path.read_text())


def candidate_integrity_failures(checkout: Path, target: ReviewTarget) -> list[str]:
    """Verify a review ref checked out at *checkout* (HEAD = PR head, origin =
    the kb remote) against current origin/main. Returns every violation as an
    agent-readable line; empty means the candidate is sound.

    The CI twin of the `review merge` guards: exactly one added file at the
    final path, Status in-review, byte-equal to what the draft on main
    derives, and the draft still present (a cancelled or landed slug has
    none — merging would land a ghost). Pure git against FETCH_HEAD; no temp
    clone, no gh. Raises RuntimeError when main cannot be fetched.
    """
    allow = file_transport_args(cwd=checkout)
    r = run_git(*allow, "fetch", "-q", "origin", "main", check=False, cwd=checkout)
    if r.returncode != 0:
        raise RuntimeError("\n".join(explain_failure("fetch kb main", r)))

    def show(ref: str, rel: str) -> str | None:
        s = run_git("show", f"{ref}:{rel}", check=False, cwd=checkout)
        return s.stdout if s.returncode == 0 else None

    failures: list[str] = []
    diff = run_git("diff", "--name-status", "FETCH_HEAD...HEAD", cwd=checkout).stdout
    if diff.splitlines() != [f"A\t{target.final_rel}"]:
        failures.append(
            f"PR must add exactly one file, '{target.final_rel}' — diff vs main:\n"
            + (diff.rstrip() or "(empty)")
            + f"\n  fix: rcorn review push {target.slug} rebuilds the ref from the draft"
        )
    if show("FETCH_HEAD", target.final_rel) is not None:
        failures.append(
            f"'{target.final_rel}' already exists on kb main — the slug landed "
            "or collides with another doc; close this PR"
        )
    draft = show("FETCH_HEAD", target.draft_rel)
    if draft is None:
        failures.append(
            f"draft '{target.draft_rel}' is no longer on kb main — the review "
            "was cancelled or already landed; close this PR"
        )
    cand = show("HEAD", target.final_rel)
    if cand is None:
        failures.append(f"candidate missing at '{target.final_rel}' on the PR head")
    else:
        status = get(cand, FIELD_STATUS)
        if status != STATUS_IN_REVIEW:
            failures.append(
                f"'{target.final_rel}' has status '{status}', expected "
                f"'{STATUS_IN_REVIEW}' — fix: rcorn review push {target.slug}"
            )
        if draft is not None and not candidate_matches(cand, draft):
            failures.append(
                f"candidate drifted from '{target.draft_rel}' on kb main — "
                f"fix: rcorn review push {target.slug}"
            )
    return failures


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
    if get(final.read_text(), FIELD_STATUS) != STATUS_APPROVED:
        stamps: dict[str, object] = {FIELD_STATUS: STATUS_APPROVED}
        if pr_url:
            stamps[FIELD_REVIEW_PR] = pr_url
        if approved_by:
            stamps[FIELD_APPROVED_BY] = approved_by
        final.write_text(set_meta(final.read_text(), stamps))
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
    last_push: GitFailure | None = None
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
            last_push = push
    if last_push is None:  # pragma: no cover - range(retries + 1) always runs
        raise RuntimeError("cleanup push never ran")
    raise RuntimeError("\n".join(explain_failure(
        "publish the post-merge cleanup (retried and still failing)", last_push,
    )))
