"""Tests for the review-lane core (no gh, no network)."""
import dataclasses
from pathlib import Path

import pytest

from reinicorn.git import gh_repo_from_url, run_git
from reinicorn.review import (
    ReviewTarget,
    candidate_matches_draft,
    candidate_text,
    cleanup_after_merge,
    pr_new_url,
    push_candidate,
    resolve_draft,
    resolve_drafts,
    review_branch,
)


def test_review_branch_is_repo_scoped():
    assert review_branch("myrepo", "spec", "my-slug") == "review/myrepo/spec-my-slug"


@pytest.mark.parametrize("url", [
    "git@github.com:owner/name-kb.git",
    "https://github.com/owner/name-kb.git",
    "https://github.com/owner/name-kb",
])
def test_gh_repo_from_url(url):
    assert gh_repo_from_url(url) == "owner/name-kb"


def test_gh_repo_from_url_non_github_is_none():
    assert gh_repo_from_url("git@gitlab.com:o/n.git") is None


def test_pr_new_url():
    assert pr_new_url("owner/kb", "review/myrepo/spec-x") == (
        "https://github.com/owner/kb/pull/new/review/myrepo/spec-x"
    )


def _mk_draft(kb_dir: Path, scope: str, slug: str) -> Path:
    d = kb_dir / scope / "specs" / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{slug}.md"
    f.write_text(f"# {slug}\n\n**Status:** draft\n")
    return f


def test_resolve_draft_by_slug(tmp_path):
    f = _mk_draft(tmp_path, "myrepo", "my-slug")
    t = resolve_draft("my-slug", tmp_path, "myrepo")
    assert isinstance(t, ReviewTarget)
    assert t.doc_type.key == "spec"
    assert t.slug == "my-slug"
    assert t.repo_scope == "myrepo"
    assert t.draft_path == f
    assert t.draft_rel == "myrepo/specs/drafts/my-slug.md"
    assert t.final_rel == "myrepo/specs/my-slug.md"
    assert t.branch == "review/myrepo/spec-my-slug"


def test_resolve_draft_accepts_path(tmp_path):
    f = _mk_draft(tmp_path, "myrepo", "my-slug")
    t = resolve_draft(str(f), tmp_path, "myrepo")
    assert t is not None and t.slug == "my-slug"


def test_resolve_draft_missing_returns_none(tmp_path):
    (tmp_path / "myrepo").mkdir()
    assert resolve_draft("nope", tmp_path, "myrepo") is None


def test_resolve_drafts_type_filter(tmp_path):
    _mk_draft(tmp_path, "myrepo", "my-slug")
    assert len(resolve_drafts("my-slug", tmp_path, "myrepo", type_key="spec")) == 1
    assert resolve_drafts("my-slug", tmp_path, "myrepo", type_key="prd") == []


def test_candidate_text_flips_status():
    out = candidate_text("# T\n\n**Status:** draft\n\nbody\n")
    assert "**Status:** in-review" in out
    assert "body" in out


def _remote_file(bare, ref, rel):
    r = run_git("show", f"{ref}:{rel}", cwd=bare, check=False)
    return r.stdout if r.returncode == 0 else None


def test_push_candidate_creates_ref_with_only_final_file(kb_pair):
    bare, local = kb_pair
    t = resolve_draft("x", local, "myrepo")
    assert t is not None
    push_candidate(local, t)
    cand = _remote_file(bare, t.branch, "myrepo/specs/x.md")
    assert cand and "**Status:** in-review" in cand
    # draft untouched on the ref (add-only: rename detection must find no delete)
    assert _remote_file(bare, t.branch, "myrepo/specs/drafts/x.md") is not None


def test_push_candidate_updates_existing_ref(kb_pair):
    bare, local = kb_pair
    t = resolve_draft("x", local, "myrepo")
    assert t is not None
    push_candidate(local, t)
    (local / "myrepo/specs/drafts/x.md").write_text(
        "# X\n\n**Status:** draft\n\n## Problem\n\nrevised\n"
    )
    push_candidate(local, t)
    cand = _remote_file(bare, t.branch, "myrepo/specs/x.md")
    assert cand and "revised" in cand


def test_push_candidate_rejects_invalid_ref(kb_pair):
    _bare, local = kb_pair
    t0 = resolve_draft("x", local, "myrepo")
    assert t0 is not None
    t = dataclasses.replace(t0, branch="review/bad name")
    with pytest.raises(RuntimeError, match="invalid review ref"):
        push_candidate(local, t)


def test_cleanup_after_merge_flips_stamps_deletes(kb_pair):
    bare, local = kb_pair
    t = resolve_draft("x", local, "myrepo")
    assert t is not None
    push_candidate(local, t)
    run_git("fetch", "-q", "origin", t.branch, cwd=local)
    run_git("push", "-q", "origin", f"origin/{t.branch}:main", cwd=local)
    assert cleanup_after_merge(local, t, pr_url="https://x/pull/1",
                               approved_by="alice") is True
    final = _remote_file(bare, "main", "myrepo/specs/x.md")
    assert final is not None
    assert "**Status:** approved" in final
    assert "**Review-PR:** https://x/pull/1" in final
    assert "**Approved-by:** alice" in final
    assert _remote_file(bare, "main", "myrepo/specs/drafts/x.md") is None
    # idempotent second run is a no-op
    assert cleanup_after_merge(local, t, pr_url="https://x/pull/1") is False


def test_cleanup_after_merge_deletes_review_ref(kb_pair):
    """Ref gardening: merges reins didn't perform (browser merge + CI
    cleanup) would otherwise leave review/* branches piling up on the
    remote — a successful finalize deletes the merged ref."""
    bare, local = kb_pair
    t = resolve_draft("x", local, "myrepo")
    assert t is not None
    push_candidate(local, t)
    run_git("fetch", "-q", "origin", t.branch, cwd=local)
    run_git("push", "-q", "origin", f"origin/{t.branch}:main", cwd=local)
    assert cleanup_after_merge(local, t, pr_url="https://x/pull/1") is True
    refs = run_git("ls-remote", "--heads", str(bare), t.branch).stdout
    assert refs.strip() == ""


def test_divergence_detection(kb_pair):
    _bare, local = kb_pair
    t = resolve_draft("x", local, "myrepo")
    assert t is not None
    push_candidate(local, t)
    assert candidate_matches_draft(local, t) is True
    (local / "myrepo/specs/drafts/x.md").write_text(
        "# X\n\n**Status:** draft\n\nchanged\n"
    )
    assert candidate_matches_draft(local, t) is False


def test_push_candidate_failure_surfaces_stderr(kb_pair):
    # Simulate a remote-side push failure with a pre-receive hook on the
    # bare remote (more robust than chmod -R a-w, which is a no-op when
    # tests run as root, e.g. in containers; hooks only fire on push, so
    # the clone inside push_candidate still works).
    bare, local = kb_pair
    t = resolve_draft("x", local, "myrepo")
    assert t is not None
    hook = bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'rejected by test hook' >&2\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(RuntimeError, match="review ref push failed") as exc:
        push_candidate(local, t)
    assert "rejected by test hook" in str(exc.value)


def test_missing_origin_remote_raises(tmp_path):
    kb = tmp_path / "kb-no-origin"
    kb.mkdir()
    run_git("init", "-q", "-b", "main", str(kb))
    _mk_draft(kb, "myrepo", "x")
    t = resolve_draft("x", kb, "myrepo")
    assert t is not None
    with pytest.raises(RuntimeError, match="no origin remote"):
        push_candidate(kb, t)
    with pytest.raises(RuntimeError, match="no origin remote"):
        cleanup_after_merge(kb, t, pr_url="")


def test_make_target_derives_all_paths():
    """Single source for draft/final path algebra (shared with _review-cleanup)."""
    from reinicorn.doc_types import REGISTRY
    from reinicorn.review import make_target

    t = make_target(REGISTRY["spec"], "myrepo", "my-slug", Path("/kb"))
    assert t.draft_path == Path("/kb/myrepo/specs/drafts/my-slug.md")
    assert t.draft_rel == "myrepo/specs/drafts/my-slug.md"
    assert t.final_rel == "myrepo/specs/my-slug.md"
    assert t.branch == "review/myrepo/spec-my-slug"


def test_push_candidate_refuses_slug_collision_with_landed_doc(kb_pair):
    """A doc already at the final path on main means this slug is taken —
    the lane must refuse loudly, not emit the generic add-only error."""
    _bare, local = kb_pair
    (local / "myrepo/specs/x.md").write_text("# X\n\n**Status:** approved\n")
    run_git("add", "-A", cwd=local)
    run_git("commit", "-q", "-m", "landed", cwd=local)
    run_git("push", "-q", "origin", "main", cwd=local)
    t = resolve_draft("x", local, "myrepo")
    assert t is not None
    with pytest.raises(RuntimeError, match="already exists on kb main"):
        push_candidate(local, t)


def test_remote_main_state(kb_pair):
    from reinicorn.review import remote_main_state

    _bare, local = kb_pair
    t = resolve_draft("x", local, "myrepo")
    assert t is not None
    final, draft = remote_main_state(local, t)
    assert final is None
    assert draft is not None and "**Status:** draft" in draft

    push_candidate(local, t)
    run_git("fetch", "-q", "origin", t.branch, cwd=local)
    run_git("push", "-q", "origin", f"origin/{t.branch}:main", cwd=local)
    final, draft = remote_main_state(local, t)
    assert final is not None and "**Status:** in-review" in final
    assert draft is not None


def test_cleanup_without_landed_final_never_deletes_draft(kb_pair):
    """cleanup on a ref whose candidate never landed must be a no-op — deleting
    the draft when nothing merged would destroy unreviewed work."""
    bare, local = kb_pair
    t = resolve_draft("x", local, "myrepo")
    assert t is not None
    assert cleanup_after_merge(local, t, pr_url="https://x/pull/1") is False
    assert _remote_file(bare, "main", "myrepo/specs/drafts/x.md") is not None
