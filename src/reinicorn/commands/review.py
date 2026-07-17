"""Reinicorn review — doc-review lane verbs (start, push, merge, cancel, link, status).

Axi channels: the PR URL is data → bare print() on stdout; warnings via
console.warn; progress only on stderr; every error is followed by an
actionable next step where one exists.

gh gates conveniences, never the lane: the git half (review ref, stamps)
always happens, and without gh the human gets the exact URL plus the
follow-up command for the GitHub half.
"""

from __future__ import annotations

import functools
import subprocess
from datetime import date
from typing import TYPE_CHECKING

from reinicorn import console, github
from reinicorn.config import kb_scope
from reinicorn.docmeta import (
    FIELD_REVIEW_CANCELLED,
    FIELD_REVIEW_PR,
    FIELD_STATUS,
    STATUS_DRAFT,
    STATUS_IN_REVIEW,
    get_field,
    remove_field,
    set_field,
)
from reinicorn.git import (
    file_transport_args,
    gh_repo_from_url,
    remote_url,
    repo_root,
    run_git,
)
from reinicorn.kb import commit_kb, ensure_kb_on_main, push_main_with_retry, require_kb_dir
from reinicorn.meta import reinicorn_source_repo
from reinicorn.mode import can_publish, get_mode
from reinicorn.review import (
    candidate_matches_draft,
    cleanup_after_merge,
    collect_gated_drafts,
    delete_review_ref,
    pr_new_url,
    push_candidate,
    remote_main_state,
    resolve_drafts,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from reinicorn.review import ReviewTarget


def _surfacing_errors[**P](fn: Callable[P, int]) -> Callable[P, int]:
    """Surface remote/git failures as structured errors — never raw tracebacks.

    RuntimeError is the review.py/github.py error contract for remote-facing
    failures; CalledProcessError covers local temp-clone git ops.
    """
    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> int:
        try:
            return fn(*args, **kwargs)
        except RuntimeError as e:
            console.error(str(e))
            return 1
        except subprocess.CalledProcessError as e:
            console.error(f"git failed: {e}\n{(e.stderr or '').strip()}")
            return 1
    return wrapper


def _mode_blocked() -> bool:
    if can_publish():
        return False
    console.error(f"Review blocked (mode: {get_mode()}).")
    console.next_step("rcorn mode enable")
    return True


def _gh_ready() -> bool:
    return github.gh_available() and github.gh_authenticated()


def _ctx(slug_or_path: str, type_key: str | None) -> tuple[Path, Path, ReviewTarget] | None:
    """(root, kb_dir, target) for a uniquely-resolved draft, or None (error printed)."""
    root = repo_root()
    if root is None:
        return None
    kb_dir = require_kb_dir(root)
    ensure_kb_on_main(kb_dir)
    matches = resolve_drafts(slug_or_path, kb_dir, kb_scope(root), type_key)
    if not matches:
        console.error(f"no draft named '{slug_or_path}'")
        console.next_step("rcorn spec list --include-drafts")
        return None
    if len(matches) > 1:
        keys = ", ".join(sorted(t.doc_type.key for t in matches))
        console.error(f"'{slug_or_path}' matches drafts of multiple types: {keys}")
        console.next_step(f"rerun with --type ({keys})")
        return None
    return root, kb_dir, matches[0]


def _push_kb_main(kb_dir: Path) -> None:
    """Publish kb main, surfacing a failed push as an agent-readable error."""
    push = push_main_with_retry(kb_dir)
    if push.returncode != 0:
        raise RuntimeError(f"kb push failed: {push.stderr.strip()}")


def _stamp_draft(
    root: Path, kb_dir: Path, target: ReviewTarget,
    message: str, fields: dict[str, str | None],
) -> None:
    """Set (or remove, when value is None) header fields on the on-main draft.

    Commits AND publishes kb main — the stamps (in-review status, Review-PR)
    only do their job when teammates and `kb status` can see them, and an
    unpublished stamp commit would conflict with the post-merge cleanup pull.
    """
    text = target.draft_path.read_text()
    for field, value in fields.items():
        text = remove_field(text, field) if value is None else set_field(text, field, value)
    target.draft_path.write_text(text)
    # commit_kb sweeps any other pending kb changes into this commit by design —
    # kb main is always publishable, so bystander edits ride along rather than block.
    commit_kb(root, message, kb_dir=kb_dir)
    _push_kb_main(kb_dir)


def _doc_title(target: ReviewTarget) -> str:
    for line in target.draft_path.read_text().splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return target.slug


def _pull_kb_main(kb_dir: Path) -> None:
    run_git(*file_transport_args(cwd=kb_dir), "pull", "-q", "--no-rebase",
            "origin", "main", check=False, cwd=kb_dir)


@_surfacing_errors
def cmd_review_start(slug: str, reviewers: list[str], type_key: str | None = None) -> int:
    if _mode_blocked():
        return 1
    ctx = _ctx(slug, type_key)
    if ctx is None:
        return 1
    root, kb_dir, target = ctx
    console.progress(f"Pushing review candidate for {target.slug}...")
    push_candidate(kb_dir, target)
    gh_repo = gh_repo_from_url(remote_url(kb_dir))
    message = f"review({target.doc_type.key}): start {target.slug}"
    if gh_repo and _gh_ready():
        pr_url = github.gh_pr_create(
            gh_repo,
            head=target.branch,
            title=f"[doc-review] {target.doc_type.key}: {_doc_title(target)}",
            body=(
                f"Review candidate for `{target.final_rel}`.\n\n"
                "Opened by the Reinicorn doc-review lane. Approve, then run "
                f"`rcorn review merge {target.slug}` to land the doc."
            ),
            reviewers=reviewers or None,
        )
        # Review-cancelled: None clears the gardening marker on restart.
        _stamp_draft(root, kb_dir, target, message, {
            FIELD_STATUS: STATUS_IN_REVIEW,
            FIELD_REVIEW_PR: pr_url,
            FIELD_REVIEW_CANCELLED: None,
        })
        # Re-sync the ref to the stamped draft, so the very next `review
        # merge` doesn't trip the divergence guard on the header stamps.
        # No approvals exist seconds after PR creation, so nothing is dismissed.
        push_candidate(kb_dir, target)
        print(pr_url)
        console.next_step("rcorn review status")
        return 0
    # No-gh escape hatch: the ref is pushed either way; the human opens the PR.
    _stamp_draft(root, kb_dir, target, message, {
        FIELD_STATUS: STATUS_IN_REVIEW,
        FIELD_REVIEW_PR: None,
        FIELD_REVIEW_CANCELLED: None,
    })
    push_candidate(kb_dir, target)  # keep the ref in sync with the stamped draft
    console.warn("gh unavailable — review ref pushed, PR must be opened manually.")
    if gh_repo:
        print(pr_new_url(gh_repo, target.branch))
    console.next_step(f"rcorn review link {target.slug} <pr-url>")
    return 0


@_surfacing_errors
def cmd_review_push(slug: str, type_key: str | None = None) -> int:
    if _mode_blocked():
        return 1
    ctx = _ctx(slug, type_key)
    if ctx is None:
        return 1
    _root, kb_dir, target = ctx
    push_candidate(kb_dir, target)
    console.success("Candidate updated on the review ref.")
    pr_url = get_field(target.draft_path.read_text(), FIELD_REVIEW_PR)
    if pr_url:
        console.warn(
            "If the kb repo dismisses stale approvals (rcorn review setup), "
            "reviewers must re-approve."
        )
        print(pr_url)
    return 0


@_surfacing_errors
def cmd_review_link(slug: str, pr_url: str, type_key: str | None = None) -> int:
    if _mode_blocked():
        return 1
    ctx = _ctx(slug, type_key)
    if ctx is None:
        return 1
    root, kb_dir, target = ctx
    _stamp_draft(
        root, kb_dir, target,
        f"review({target.doc_type.key}): link {target.slug}",
        {FIELD_STATUS: STATUS_IN_REVIEW, FIELD_REVIEW_PR: pr_url},
    )
    # Re-sync the ref to the stamped draft so the Review-PR header line
    # doesn't trip the divergence guard on the next merge.
    push_candidate(kb_dir, target)
    console.success(f"Linked {pr_url}")
    return 0


@_surfacing_errors
def cmd_review_merge(slug: str, type_key: str | None = None, force: bool = False) -> int:
    if _mode_blocked():
        return 1
    ctx = _ctx(slug, type_key)
    if ctx is None:
        return 1
    _root, kb_dir, target = ctx
    pr_url = get_field(target.draft_path.read_text(), FIELD_REVIEW_PR) or ""
    approved_by = ""
    final_text, remote_draft = remote_main_state(kb_dir, target)
    merged = (
        final_text is not None
        and get_field(final_text, FIELD_STATUS) == STATUS_IN_REVIEW
    )
    if final_text is not None and not merged:
        if remote_draft is None:
            # A previous cleanup (CI after a browser merge, or another
            # machine) already landed and finalized this review.
            console.info(f"already landed at {target.final_rel} — syncing local kb")
            _pull_kb_main(kb_dir)
            return 0
        console.error(
            f"'{target.final_rel}' on kb main is already occupied by a doc "
            f"with status '{get_field(final_text, FIELD_STATUS) or 'unknown'}' "
            "— slug collision; this draft was never reviewed there."
        )
        console.next_step("recreate the draft under a new title")
        return 1
    if not merged:
        if not candidate_matches_draft(kb_dir, target) and not force:
            console.error(
                "draft has changed since the last 'review push' — "
                "the PR does not show what you'd be approving."
            )
            console.next_step(
                f"rcorn review push {target.slug}",
                f"rcorn review merge {target.slug} --force",
            )
            return 1
        gh_repo = gh_repo_from_url(remote_url(kb_dir))
        if gh_repo and _gh_ready():
            pr = github.gh_pr_view(gh_repo, head=target.branch)
            if pr is None:
                console.error("no PR found for the review ref")
                console.next_step(f"rcorn review link {target.slug} <pr-url>")
                return 1
            decision = pr.get("reviewDecision") or ""
            if decision != github.REVIEW_DECISION_APPROVED and not force:
                if decision:
                    console.error(f"PR is not approved (decision: {decision}).")
                    print(pr["url"])
                else:
                    # GitHub only populates reviewDecision when a required-review
                    # rule exists; without one (setup not run, or its best-effort
                    # ruleset failed) the decision is empty even after approval.
                    console.error(
                        "PR approval state unknown — the kb repo has no "
                        "required-review rule, so GitHub reports no decision."
                    )
                    print(pr["url"])
                    console.info(
                        "Verify approvals on the PR, then rerun with --force; "
                        "rcorn review setup installs the ruleset."
                    )
                    console.next_step(f"rcorn review merge {target.slug} --force")
                return 1
            github.gh_pr_merge(gh_repo, pr["number"])
            pr_url = pr["url"]
            approved_by = ", ".join(sorted({
                r["author"]["login"]
                for r in pr.get("latestReviews") or []
                if r.get("state") == github.REVIEW_DECISION_APPROVED
            }))
        else:
            console.warn("gh unavailable — merge the PR in the GitHub UI, then rerun.")
            if pr_url:
                print(pr_url)
            console.next_step(f"rcorn review merge {target.slug}")
            return 1
    if cleanup_after_merge(kb_dir, target, pr_url=pr_url, approved_by=approved_by):
        console.success(f"{target.slug} approved and landed at {target.final_rel}")
    else:
        console.info("already cleaned up — nothing to do")
    _pull_kb_main(kb_dir)
    return 0


@_surfacing_errors
def cmd_review_cancel(slug: str, type_key: str | None = None) -> int:
    if _mode_blocked():
        return 1
    ctx = _ctx(slug, type_key)
    if ctx is None:
        return 1
    root, kb_dir, target = ctx
    pr_url = get_field(target.draft_path.read_text(), FIELD_REVIEW_PR) or ""
    gh_repo = gh_repo_from_url(remote_url(kb_dir))
    if gh_repo and _gh_ready():
        pr = github.gh_pr_view(gh_repo, head=target.branch)
        if pr is not None and pr.get("state") == github.PR_STATE_OPEN:
            github.gh_pr_close(gh_repo, pr["number"], comment="Review cancelled via Reinicorn.")
        elif pr is None:
            console.warn("no PR found for the review ref — close it manually if one exists:")
            if pr_url:
                print(pr_url)
    elif pr_url:
        console.warn("gh unavailable — close the PR manually:")
        print(pr_url)
    if not delete_review_ref(kb_dir, target):
        console.warn("review ref could not be deleted — remove it manually")
    # Review-PR is kept on purpose: the closed PR link is the gardening trail.
    _stamp_draft(
        root, kb_dir, target,
        f"review({target.doc_type.key}): cancel {target.slug}",
        {FIELD_STATUS: STATUS_DRAFT, FIELD_REVIEW_CANCELLED: date.today().isoformat()},
    )
    console.success(f"review cancelled — {target.slug} back to draft")
    return 0


def cmd_review_status() -> int:
    """List gated-type drafts in the current repo scope. Pure local reads — no gh."""
    root = repo_root()
    if root is None:
        return 1
    kb_dir = require_kb_dir(root)
    rows = collect_gated_drafts(kb_dir / kb_scope(root))
    # "N open" only when empty — nonzero rows include plain drafts, not just
    # open reviews, so the bare count is the honest header.
    print("doc reviews: 0 open" if not rows else f"doc reviews: {len(rows)}")
    for row in rows:
        console.info(
            f"{row.key}/{row.slug} [{row.status}]"
            + (f" {row.review_pr}" if row.review_pr else "")
        )
    return 0


_WORKFLOW_ASSET = "workflows/reinicorn-doc-review-cleanup.yml"
_WORKFLOW_DEST = ".github/workflows/reinicorn-doc-review-cleanup.yml"
_REPO_PLACEHOLDER = "__REINICORN_REPO__"

_RULESET = {
    "name": "reinicorn-doc-review",
    "target": "branch",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
    "rules": [{
        "type": "pull_request",
        "parameters": {
            "required_approving_review_count": 1,
            "dismiss_stale_reviews_on_push": True,
            "require_code_owner_review": False,
            "require_last_push_approval": False,
            "required_review_thread_resolution": False,
            "allowed_merge_methods": ["squash", "merge"],
        },
    }],
    # Admin (5) and maintain (4) bypass so direct `kb publish` pushes to main
    # keep working; PR merges still get dismiss-stale. IDs are GitHub's fixed
    # RepositoryRole mapping (1=read 2=triage 3=write 4=maintain 5=admin).
    "bypass_actors": [
        {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"},
        {"actor_id": 4, "actor_type": "RepositoryRole", "bypass_mode": "always"},
    ],
}


def cmd_review_setup(force: bool = False) -> int:
    """Install the doc-review CI cleanup workflow and a best-effort ruleset.

    Not mode-gated: this configures the kb repo's automation, it doesn't
    publish docs. It does commit_kb + suggest a publish for the workflow file.
    """
    root = repo_root()
    if root is None:
        return 1
    kb_dir = require_kb_dir(root)
    from reinicorn.assets import get_asset_path
    src = get_asset_path(_WORKFLOW_ASSET)
    if src is None:
        console.error(f"bundled asset missing: {_WORKFLOW_ASSET}")
        return 1
    dest = kb_dir / _WORKFLOW_DEST
    source_repo = reinicorn_source_repo()
    if source_repo is None:
        console.error(
            "cannot derive the Reinicorn source repo from package metadata "
            "(Project-URL: Repository) — the CI workflow needs it to "
            "install Reinicorn"
        )
        return 1
    template = src.read_text().replace(_REPO_PLACEHOLDER, source_repo)
    if dest.is_file() and dest.read_text() != template and not force:
        console.error("workflow file was modified — rerun with --force to overwrite")
        return 1
    if not dest.is_file() or dest.read_text() != template:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(template)
        commit_kb(root, "chore(kb): install Reinicorn doc-review cleanup workflow", kb_dir=kb_dir)
        console.success(f"workflow installed: kb/{_WORKFLOW_DEST}")
        console.next_step("rcorn kb publish")
    else:
        console.info("workflow already up to date")

    # Best-effort ruleset (dismiss stale approvals). Reinicorn's own divergence
    # check remains the guardrail floor when this can't be applied.
    gh_repo = gh_repo_from_url(remote_url(kb_dir))
    if gh_repo and _gh_ready():
        import json
        r = github.run_gh(
            "api", f"repos/{gh_repo}/rulesets", "--method", "POST",
            "--input", "-", check=False, input_text=json.dumps(_RULESET),
        )
        if r.returncode == 0:
            console.success("dismiss-stale-approvals ruleset applied")
        else:
            console.warn(
                "ruleset not applied (plan/permissions?) — Reinicorn's own "
                "divergence check remains the guardrail"
            )
    else:
        console.warn("gh unavailable — ruleset skipped; apply manually if wanted")
    return 0
