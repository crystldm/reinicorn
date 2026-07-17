"""Tests for reins _review-cleanup — kb-repo CI post-merge entry point."""

from __future__ import annotations

from pathlib import Path

import pytest

from reinicorn.git import run_git
from reinicorn.review import push_candidate, resolve_draft


def _remote_file(bare: Path, ref: str, rel: str) -> str | None:
    r = run_git("show", f"{ref}:{rel}", cwd=bare, check=False)
    return r.stdout if r.returncode == 0 else None


@pytest.fixture
def merged_checkout(kb_pair, tmp_path: Path) -> Path:
    """A fresh clone of the kb-remote after a review PR has "merged".

    Reproduces exactly the state a GitHub Actions checkout of main would see
    right after a review/* PR merges: the candidate exists at the final path
    AND the draft copy is still present on main (cleanup hasn't run yet).
    """
    bare, local = kb_pair
    t = resolve_draft("x", local, "myrepo")
    assert t is not None
    push_candidate(local, t)

    # Simulate the PR merge: fast-forward main to the review ref, entirely
    # inside the bare remote (no working tree involved).
    run_git("branch", "-f", "main", t.branch, cwd=bare)

    # This is the Actions checkout: a fresh clone with cwd at its root.
    checkout = tmp_path / "checkout"
    run_git("clone", "-q", str(bare), str(checkout))
    run_git("config", "user.email", "test@test.com", cwd=checkout)
    run_git("config", "user.name", "Test User", cwd=checkout)

    return checkout


def test_cleanup_from_ref_name(merged_checkout: Path, kb_pair, monkeypatch):
    bare, _local = kb_pair
    monkeypatch.chdir(merged_checkout)

    from reinicorn.commands.internal.review_cleanup import cmd_review_cleanup

    assert cmd_review_cleanup(["review/myrepo/spec-x", "https://x/pull/1"]) == 0

    final = _remote_file(bare, "main", "myrepo/specs/x.md")
    assert final is not None
    assert "**Status:** approved" in final
    assert "**Review-PR:** https://x/pull/1" in final
    assert _remote_file(bare, "main", "myrepo/specs/drafts/x.md") is None


def test_cleanup_is_idempotent(merged_checkout: Path, kb_pair, monkeypatch):
    _bare, _local = kb_pair
    monkeypatch.chdir(merged_checkout)

    from reinicorn.commands.internal.review_cleanup import cmd_review_cleanup

    assert cmd_review_cleanup(["review/myrepo/spec-x", "https://x/pull/1"]) == 0
    # second run against the now-stale checkout is still a successful no-op
    assert cmd_review_cleanup(["review/myrepo/spec-x", "https://x/pull/1"]) == 0


def test_cleanup_skips_nonlane_ref(monkeypatch, tmp_path, capsys):
    """rc 0 with an explicit skip line — the workflow's if: only filters on
    the review/ prefix, so any merged branch under it reaches us; a non-lane
    ref must not produce a red CI run."""
    monkeypatch.chdir(tmp_path)
    from reinicorn.commands.internal.review_cleanup import cmd_review_cleanup

    assert cmd_review_cleanup(["not-a-review-ref"]) == 0
    assert "skip" in capsys.readouterr().out.lower()


def test_cleanup_missing_args(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from reinicorn.commands.internal.review_cleanup import cmd_review_cleanup

    assert cmd_review_cleanup([]) == 1


def test_cleanup_unknown_doc_type_skips(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    from reinicorn.commands.internal.review_cleanup import cmd_review_cleanup

    assert cmd_review_cleanup(["review/myrepo/bogus-x"]) == 0
    assert "skip" in capsys.readouterr().out.lower()


def test_cleanup_no_origin_returns_clean_error(monkeypatch, tmp_path, capsys):
    """A checkout with no origin remote → rc 1 + clean error line, no traceback."""
    repo = tmp_path / "checkout"
    repo.mkdir()
    run_git("init", "-q", "-b", "main", str(repo))
    run_git("config", "user.email", "t@t.com", cwd=repo)
    run_git("config", "user.name", "T", cwd=repo)
    monkeypatch.chdir(repo)

    from reinicorn.commands.internal.review_cleanup import cmd_review_cleanup

    assert cmd_review_cleanup(["review/myrepo/spec-x", "https://x/pull/1"]) == 1
    out = capsys.readouterr().out
    assert "error:" in out
    assert "Traceback" not in out


def test_cli_main_dispatches_review_cleanup(monkeypatch, tmp_path):
    """`reins _review-cleanup ...` is wired through cli.main's internal dispatch."""
    monkeypatch.chdir(tmp_path)
    from reinicorn.cli import main

    # no args → usage error, proving the argv tail reaches cmd_review_cleanup
    assert main(["_review-cleanup"]) == 1
