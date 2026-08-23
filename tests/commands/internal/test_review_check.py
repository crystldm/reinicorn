"""Tests for rcorn _review-check — kb-repo CI candidate-integrity check.

Every scenario is run end to end against a clone that reproduces the
Actions checkout: the PR head checked out at the root, origin pointing at
the kb remote, cwd at the checkout root.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import doc_text

from reinicorn import frontmatter as fm
from reinicorn.git import run_git
from reinicorn.review import push_candidate, resolve_draft

_REF = "review/myrepo/spec-x"


def _commit_push_main(local: Path, message: str) -> None:
    run_git("add", "-A", cwd=local)
    run_git("commit", "-q", "-m", message, cwd=local)
    run_git("push", "-q", "origin", "main", cwd=local)


@pytest.fixture
def pr_checkout(kb_pair, tmp_path: Path) -> tuple[Path, Path, Path]:
    """(bare, local, checkout): a review ref pushed for draft x, and a fresh
    clone of the remote with that ref checked out — the Actions checkout a
    `pull_request` run sees."""
    bare, local = kb_pair
    t = resolve_draft("x", local, "myrepo")
    assert t is not None
    push_candidate(local, t)

    checkout = tmp_path / "checkout"
    run_git("clone", "-q", "-b", t.branch, str(bare), str(checkout))
    run_git("config", "user.email", "test@test.com", cwd=checkout)
    run_git("config", "user.name", "Test User", cwd=checkout)
    return bare, local, checkout


def _run(monkeypatch, checkout: Path, args: list[str]) -> int:
    monkeypatch.chdir(checkout)
    from reinicorn.commands.internal.review_check import cmd_review_check
    return cmd_review_check(args)


def test_healthy_candidate_passes(pr_checkout, monkeypatch, capsys):
    _bare, _local, checkout = pr_checkout
    assert _run(monkeypatch, checkout, [_REF]) == 0
    assert "error" not in capsys.readouterr().out.lower()


def test_drifted_draft_fails(pr_checkout, monkeypatch, capsys):
    """The draft on main changed after the candidate was pushed — the PR
    shows stale content and must go red until `review push` refreshes it."""
    _bare, local, checkout = pr_checkout
    draft = local / "myrepo" / "specs" / "drafts" / "x.md"
    draft.write_text(doc_text(body="\n## Problem\n\nrevised\n"))
    _commit_push_main(local, "revise draft")

    assert _run(monkeypatch, checkout, [_REF]) == 1
    out = capsys.readouterr().out
    assert "drift" in out.lower()
    assert "rcorn review push x" in out


def test_extra_file_in_pr_fails(pr_checkout, monkeypatch, capsys):
    _bare, _local, checkout = pr_checkout
    (checkout / "myrepo" / "specs" / "other.md").write_text(doc_text(slug="other"))
    run_git("add", "-A", cwd=checkout)
    run_git("commit", "-q", "-m", "smuggle", cwd=checkout)

    assert _run(monkeypatch, checkout, [_REF]) == 1
    out = capsys.readouterr().out
    assert "exactly one" in out
    assert "myrepo/specs/other.md" in out


def test_wrong_status_fails(pr_checkout, monkeypatch, capsys):
    _bare, _local, checkout = pr_checkout
    cand = checkout / "myrepo" / "specs" / "x.md"
    cand.write_text(fm.set_meta(cand.read_text(), {"status": "approved"}))
    run_git("add", "-A", cwd=checkout)
    run_git("commit", "-q", "-m", "pre-approve", cwd=checkout)

    assert _run(monkeypatch, checkout, [_REF]) == 1
    out = capsys.readouterr().out
    assert "in-review" in out
    assert "approved" in out


def test_draft_gone_from_main_fails(pr_checkout, monkeypatch, capsys):
    """A cancelled or already-landed slug has no draft on main — merging the
    PR would land a ghost, so the check is red rather than vacuously green."""
    _bare, local, checkout = pr_checkout
    run_git("rm", "-q", "myrepo/specs/drafts/x.md", cwd=local)
    _commit_push_main(local, "cancel x")

    assert _run(monkeypatch, checkout, [_REF]) == 1
    assert "draft" in capsys.readouterr().out.lower()


def test_final_path_already_on_main_fails(pr_checkout, monkeypatch, capsys):
    _bare, local, checkout = pr_checkout
    (local / "myrepo" / "specs" / "x.md").write_text(doc_text(status="approved"))
    _commit_push_main(local, "landed x some other way")

    assert _run(monkeypatch, checkout, [_REF]) == 1
    assert "already" in capsys.readouterr().out.lower()


def test_all_failures_reported_together(pr_checkout, monkeypatch, capsys):
    """One run lists every violation — an agent fixing the PR should not
    need a round trip per problem."""
    _bare, local, checkout = pr_checkout
    run_git("rm", "-q", "myrepo/specs/drafts/x.md", cwd=local)
    _commit_push_main(local, "cancel x")
    (checkout / "myrepo" / "specs" / "other.md").write_text(doc_text(slug="other"))
    run_git("add", "-A", cwd=checkout)
    run_git("commit", "-q", "-m", "smuggle", cwd=checkout)

    assert _run(monkeypatch, checkout, [_REF]) == 1
    out = capsys.readouterr().out.lower()
    assert "draft" in out
    assert "exactly one" in out


def test_nonlane_ref_skips(monkeypatch, tmp_path, capsys):
    """The workflow runs on every PR; a non-lane branch is a skip (rc 0),
    never a red check."""
    assert _run(monkeypatch, tmp_path, ["feature/not-a-review"]) == 0
    assert "skip" in capsys.readouterr().out.lower()


def test_unknown_doc_type_skips(monkeypatch, tmp_path, capsys):
    assert _run(monkeypatch, tmp_path, ["review/myrepo/bogus-x"]) == 0
    assert "skip" in capsys.readouterr().out.lower()


def test_missing_args(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, []) == 1


def test_no_origin_returns_clean_error(monkeypatch, tmp_path, capsys):
    repo = tmp_path / "checkout"
    repo.mkdir()
    run_git("init", "-q", "-b", "main", str(repo))

    assert _run(monkeypatch, repo, [_REF]) == 1
    out = capsys.readouterr().out
    assert "error:" in out
    assert "Traceback" not in out


def test_cli_main_dispatches_review_check(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from reinicorn.cli import main

    # rc 0 is reachable only through cmd_review_check's skip path; the
    # unmatched fall-through in _dispatch_internal always returns 1.
    assert main(["_review-check", "feature/not-a-review"]) == 0
    assert main(["_review-check"]) == 1
