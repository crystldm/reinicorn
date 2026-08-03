"""Tests for the Reinicorn review CLI verbs (no network, no real gh)."""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import reinicorn.commands.review as review_cmds
from reinicorn.git import run_git
from reinicorn.review import candidate_matches_draft, resolve_draft

_PR_URL = "https://github.com/owner/kb/pull/7"
_BRANCH = "review/testproject/spec-x"


@pytest.fixture
def env(submodule_repo: Path):
    """submodule_repo with repo_root/kb_scope/can_publish patched for review."""
    with patch("reinicorn.commands.review.repo_root", return_value=submodule_repo), \
         patch("reinicorn.commands.review.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.review.can_publish", return_value=True):
        yield submodule_repo


def _draft(parent: Path, slug: str = "x") -> Path:
    """Write a full-header spec draft in the kb, commit + push kb main."""
    kb = parent / "kb"
    d = kb / "testproject" / "specs" / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{slug}.md"
    f.write_text(
        f"# {slug}\n"
        "\n"
        "**Date:** 2026-01-01\n"
        "**Author:** tester\n"
        "**Status:** draft\n"
        "**Origin:** human\n"
        "\n"
        "## Problem\n"
        "\n"
        "body\n"
    )
    run_git("add", "-A", cwd=kb)
    run_git("commit", "-q", "-m", f"draft {slug}", cwd=kb)
    run_git("push", "-q", "origin", "main", cwd=kb)
    return f


def _gh(monkeypatch, *, available: bool = True, repo: str | None = "owner/kb", **funcs):
    """Mock the gh surface on reinicorn.commands.review (github module + repo derivation)."""
    gh = review_cmds.github
    monkeypatch.setattr(gh, "gh_available", lambda: available)
    monkeypatch.setattr(gh, "gh_authenticated", lambda: available)
    # Default to a multi-collaborator repo with a known login; solo tests
    # override gh_repo_is_solo. Keeps the merge path off real gh.
    monkeypatch.setattr(gh, "gh_repo_is_solo", lambda _r: False)
    monkeypatch.setattr(gh, "gh_login", lambda: "author")
    for name, fn in funcs.items():
        monkeypatch.setattr(gh, name, fn)
    monkeypatch.setattr(review_cmds, "gh_repo_from_url", lambda _url: repo)


def _pr_create(repo, *, head, title, body, reviewers=None):
    return _PR_URL


def _remote_show(remote: Path, ref: str, rel: str) -> str | None:
    r = run_git("show", f"{ref}:{rel}", cwd=remote, check=False)
    return r.stdout if r.returncode == 0 else None


# ── start ────────────────────────────────────────────────────


def test_start_happy_path(env: Path, monkeypatch, capsys):
    _draft(env)
    calls: dict = {}

    def fake_create(repo, *, head, title, body, reviewers=None):
        calls.update(repo=repo, head=head, title=title, body=body, reviewers=reviewers)
        return _PR_URL

    _gh(monkeypatch, gh_pr_create=fake_create)
    assert review_cmds.cmd_review_start("x", ["alice"]) == 0

    out = capsys.readouterr().out
    assert _PR_URL in out.splitlines()  # bare data line on stdout
    assert "next: rcorn review status" in out

    assert calls["repo"] == "owner/kb"
    assert calls["head"] == _BRANCH
    assert calls["title"] == "[doc-review] spec: x"
    assert "testproject/specs/x.md" in calls["body"]
    assert calls["reviewers"] == ["alice"]

    text = (env / "kb/testproject/specs/drafts/x.md").read_text()
    assert "**Status:** in-review" in text
    assert f"**Review-PR:** {_PR_URL}" in text

    cand = _remote_show(env.parent / "kb-remote", _BRANCH, "testproject/specs/x.md")
    assert cand is not None
    assert "**Status:** in-review" in cand

    # The stamp commit is published, not just committed locally —
    # teammates and `kb status` must see the in-review state.
    main_draft = _remote_show(
        env.parent / "kb-remote", "main", "testproject/specs/drafts/x.md"
    )
    assert main_draft is not None
    assert "**Status:** in-review" in main_draft


def test_start_without_gh_pushes_ref_and_prints_pull_url(env: Path, monkeypatch, capsys):
    _draft(env)
    _gh(monkeypatch, available=False)
    assert review_cmds.cmd_review_start("x", []) == 0

    out = capsys.readouterr().out
    assert "gh unavailable" in out
    assert f"https://github.com/owner/kb/pull/new/{_BRANCH}" in out
    assert "next: rcorn review link x <pr-url>" in out

    text = (env / "kb/testproject/specs/drafts/x.md").read_text()
    assert "**Status:** in-review" in text
    assert "Review-PR" not in text

    assert _remote_show(env.parent / "kb-remote", _BRANCH, "testproject/specs/x.md") is not None


def test_start_missing_slug(env: Path, capsys):
    assert review_cmds.cmd_review_start("nope", []) == 1
    out = capsys.readouterr().out
    assert "no draft" in out
    assert "next: rcorn spec list --include-drafts" in out


@pytest.mark.parametrize("invoke", [
    pytest.param(lambda: review_cmds.cmd_review_start("x", []), id="start"),
    pytest.param(lambda: review_cmds.cmd_review_push("x"), id="push"),
    pytest.param(lambda: review_cmds.cmd_review_merge("x"), id="merge"),
    pytest.param(lambda: review_cmds.cmd_review_link("x", _PR_URL), id="link"),
    pytest.param(lambda: review_cmds.cmd_review_cancel("x"), id="cancel"),
])
def test_mutating_verbs_blocked_by_mode(invoke, capsys):
    with patch("reinicorn.commands.review.can_publish", return_value=False), \
         patch("reinicorn.commands.review.get_mode", return_value="incognito"):
        assert invoke() == 1
    out = capsys.readouterr().out
    assert "error:" in out
    assert "incognito" in out
    assert "next: rcorn mode enable" in out


# ── push ─────────────────────────────────────────────────────


def test_push_updates_candidate_and_prints_pr_url(env: Path, monkeypatch, capsys):
    draft = _draft(env)
    _gh(monkeypatch, gh_pr_create=_pr_create)
    assert review_cmds.cmd_review_start("x", []) == 0
    draft.write_text(draft.read_text().replace("body", "revised body"))
    capsys.readouterr()

    assert review_cmds.cmd_review_push("x") == 0
    out = capsys.readouterr().out
    assert "Candidate updated on the review ref." in out
    assert "dismiss" in out
    assert _PR_URL in out

    cand = _remote_show(env.parent / "kb-remote", _BRANCH, "testproject/specs/x.md")
    assert cand is not None
    assert "revised body" in cand


# ── link ─────────────────────────────────────────────────────


def test_link_stamps_status_and_pr(env: Path, capsys):
    draft = _draft(env)
    assert review_cmds.cmd_review_link("x", _PR_URL) == 0

    text = draft.read_text()
    assert "**Status:** in-review" in text
    assert f"**Review-PR:** {_PR_URL}" in text
    assert f"Linked {_PR_URL}" in capsys.readouterr().out

    msg = run_git("log", "-1", "--format=%s", cwd=env / "kb").stdout.strip()
    assert msg == "review(spec): link x"

    # The link stamp is published to kb main, not just committed locally.
    main_draft = _remote_show(
        env.parent / "kb-remote", "main", "testproject/specs/drafts/x.md"
    )
    assert main_draft is not None
    assert f"**Review-PR:** {_PR_URL}" in main_draft


def test_link_resyncs_candidate_so_merge_guard_does_not_trip(env: Path, capsys):
    _draft(env)
    assert review_cmds.cmd_review_link("x", _PR_URL) == 0

    kb = env / "kb"
    target = resolve_draft("x", kb, "testproject")
    assert target is not None
    # The Review-PR header stamp is reflected on the review ref, so the
    # merge divergence guard has nothing to trip on.
    assert candidate_matches_draft(kb, target) is True


# ── merge ────────────────────────────────────────────────────


def test_merge_divergence_guard(env: Path, monkeypatch, capsys):
    draft = _draft(env)
    _gh(monkeypatch, gh_pr_create=_pr_create)
    assert review_cmds.cmd_review_start("x", []) == 0
    draft.write_text(draft.read_text().replace("body", "changed"))
    capsys.readouterr()

    assert review_cmds.cmd_review_merge("x") == 1
    out = capsys.readouterr().out
    assert "draft has changed" in out
    assert "next: rcorn review push x" in out
    assert "next: rcorn review merge x --force" in out


def test_merge_gh_approved_lands_doc(env: Path, monkeypatch, capsys):
    _draft(env)
    remote = env.parent / "kb-remote"
    pr = {
        "number": 7, "state": "OPEN", "reviewDecision": "APPROVED",
        "url": _PR_URL,
        "latestReviews": [{"author": {"login": "alice"}, "state": "APPROVED"}],
    }

    def fake_view(repo, *, head):
        return pr

    def fake_merge(repo, number):
        # Simulate GitHub's merge: fast-forward remote main from the review ref.
        run_git("branch", "-f", "main", _BRANCH, cwd=remote)

    _gh(monkeypatch, gh_pr_create=_pr_create, gh_pr_view=fake_view, gh_pr_merge=fake_merge)
    assert review_cmds.cmd_review_start("x", []) == 0
    capsys.readouterr()

    assert review_cmds.cmd_review_merge("x") == 0
    out = capsys.readouterr().out
    assert "x approved and landed at testproject/specs/x.md" in out

    final = _remote_show(remote, "main", "testproject/specs/x.md")
    assert final is not None
    assert "**Status:** approved" in final
    assert "**Approved-by:** alice" in final
    assert f"**Review-PR:** {_PR_URL}" in final
    assert _remote_show(remote, "main", "testproject/specs/drafts/x.md") is None

    # The post-merge pull fast-forwarded the LOCAL kb cleanly (the start
    # stamp was published, so histories never diverged): draft gone, final
    # approved, no conflict/merge state left behind.
    kb = env / "kb"
    assert not (kb / "testproject/specs/drafts/x.md").exists()
    local_final = (kb / "testproject/specs/x.md").read_text()
    assert "**Status:** approved" in local_final
    porcelain = run_git("status", "--porcelain", cwd=kb).stdout.strip()
    assert porcelain == ""


def test_merge_not_approved(env: Path, monkeypatch, capsys):
    """A real (truthy) non-approved decision blocks with 'not approved'."""
    _draft(env)
    pr = {
        "number": 7, "state": "OPEN", "reviewDecision": "CHANGES_REQUESTED",
        "url": _PR_URL, "latestReviews": [],
    }

    def fake_view(repo, *, head):
        return pr

    _gh(monkeypatch, gh_pr_create=_pr_create, gh_pr_view=fake_view)
    assert review_cmds.cmd_review_start("x", []) == 0
    capsys.readouterr()

    assert review_cmds.cmd_review_merge("x") == 1
    out = capsys.readouterr().out
    assert "not approved" in out
    assert "CHANGES_REQUESTED" in out
    assert _PR_URL in out


def test_merge_no_review_decision_explains_and_offers_force(
    env: Path, monkeypatch, capsys,
):
    """Empty reviewDecision means no required-review rule (GitHub reports no
    decision even after approval) — not 'not approved'. The user gets the
    reason and the --force escape hatch instead of a dead end."""
    _draft(env)
    pr = {
        "number": 7, "state": "OPEN", "reviewDecision": None,
        "url": _PR_URL, "latestReviews": [],
    }

    def fake_view(repo, *, head):
        return pr

    _gh(monkeypatch, gh_pr_create=_pr_create, gh_pr_view=fake_view)
    assert review_cmds.cmd_review_start("x", []) == 0
    capsys.readouterr()

    assert review_cmds.cmd_review_merge("x") == 1
    out = capsys.readouterr().out
    assert "no required-review rule" in out
    assert "not approved" not in out
    assert "next: rcorn review merge x --force" in out
    assert _PR_URL in out


def test_merge_solo_repo_self_review_confirmed(env: Path, monkeypatch, capsys):
    """Solo repo (no second reviewer possible): an explicit self-review confirm
    lands the doc and stamps Approved-by <author> (self-reviewed)."""
    _draft(env)
    remote = env.parent / "kb-remote"
    pr = {
        "number": 7, "state": "OPEN", "reviewDecision": None,
        "url": _PR_URL, "latestReviews": [],
    }

    def fake_merge(repo, number):
        run_git("branch", "-f", "main", _BRANCH, cwd=remote)

    _gh(monkeypatch, gh_pr_create=_pr_create, gh_pr_view=lambda *_a, **_k: pr,
        gh_pr_merge=fake_merge, gh_repo_is_solo=lambda _r: True,
        gh_login=lambda: "solomaint")
    monkeypatch.setattr(review_cmds.console, "confirm", lambda _p: True)
    assert review_cmds.cmd_review_start("x", []) == 0
    capsys.readouterr()

    assert review_cmds.cmd_review_merge("x") == 0
    out = capsys.readouterr().out
    assert "solo repo" in out
    assert "approved and landed" in out
    landed = _remote_show(remote, "main", "testproject/specs/x.md")
    assert landed is not None
    assert "**Approved-by:** solomaint (self-reviewed)" in landed


def test_merge_solo_repo_declined_offers_force(env: Path, monkeypatch, capsys):
    """Declining the solo self-review is not a dead-end — it points at --force
    and does not merge."""
    _draft(env)
    pr = {
        "number": 7, "state": "OPEN", "reviewDecision": None,
        "url": _PR_URL, "latestReviews": [],
    }
    merged = MagicMock()
    _gh(monkeypatch, gh_pr_create=_pr_create, gh_pr_view=lambda *_a, **_k: pr,
        gh_pr_merge=merged, gh_repo_is_solo=lambda _r: True)
    monkeypatch.setattr(review_cmds.console, "confirm", lambda _p: False)
    assert review_cmds.cmd_review_start("x", []) == 0
    capsys.readouterr()

    assert review_cmds.cmd_review_merge("x") == 1
    out = capsys.readouterr().out
    assert "solo repo" in out
    assert "next: rcorn review merge x --force" in out
    merged.assert_not_called()


def test_merge_force_without_approval_stamps_self_reviewed(env: Path, monkeypatch, capsys):
    """--force with no genuine approval records a self-review, never a phantom
    approver (honest Approved-by stamp)."""
    _draft(env)
    remote = env.parent / "kb-remote"
    pr = {
        "number": 7, "state": "OPEN", "reviewDecision": None,
        "url": _PR_URL, "latestReviews": [],
    }

    def fake_merge(repo, number):
        run_git("branch", "-f", "main", _BRANCH, cwd=remote)

    _gh(monkeypatch, gh_pr_create=_pr_create, gh_pr_view=lambda *_a, **_k: pr,
        gh_pr_merge=fake_merge, gh_login=lambda: "forcer")
    assert review_cmds.cmd_review_start("x", []) == 0
    capsys.readouterr()

    assert review_cmds.cmd_review_merge("x", force=True) == 0
    landed = _remote_show(remote, "main", "testproject/specs/x.md")
    assert landed is not None
    assert "**Approved-by:** forcer (self-reviewed)" in landed


def test_merge_force_bypasses_divergence(env: Path, monkeypatch, capsys):
    """--force merges a diverged (edited-after-start) draft without re-pushing."""
    draft = _draft(env)
    remote = env.parent / "kb-remote"
    pr = {
        "number": 7, "state": "OPEN", "reviewDecision": "APPROVED",
        "url": _PR_URL,
        "latestReviews": [{"author": {"login": "alice"}, "state": "APPROVED"}],
    }

    def fake_merge(repo, number):
        run_git("branch", "-f", "main", _BRANCH, cwd=remote)

    def fake_view(repo, *, head):
        return pr

    _gh(monkeypatch, gh_pr_create=_pr_create, gh_pr_view=fake_view, gh_pr_merge=fake_merge)
    assert review_cmds.cmd_review_start("x", []) == 0
    # Edit the draft after start → candidate no longer matches (divergence).
    draft.write_text(draft.read_text().replace("body", "changed"))
    capsys.readouterr()

    # Without --force this trips the guard; with it, the merge lands.
    assert review_cmds.cmd_review_merge("x", force=True) == 0
    out = capsys.readouterr().out
    assert "approved and landed" in out
    assert _remote_show(remote, "main", "testproject/specs/drafts/x.md") is None


def test_merge_ambiguous_slug_asks_for_type(env: Path, monkeypatch, capsys):
    """A slug matching drafts of >1 gated type errors with a --type hint."""
    def two_matches(slug_or_path, kb_dir, scope, type_key=None):
        a, b = MagicMock(), MagicMock()
        a.doc_type.key, b.doc_type.key = "spec", "prd"
        return [a, b]

    monkeypatch.setattr(review_cmds, "resolve_drafts", two_matches)
    assert review_cmds.cmd_review_merge("x") == 1
    out = capsys.readouterr().out
    assert "multiple types" in out
    assert "--type" in out


def test_merge_without_gh_not_merged(env: Path, monkeypatch, capsys):
    _draft(env)
    _gh(monkeypatch, available=False)
    assert review_cmds.cmd_review_start("x", []) == 0
    capsys.readouterr()

    assert review_cmds.cmd_review_merge("x") == 1
    out = capsys.readouterr().out
    assert "merge the PR in the GitHub UI" in out


# ── cancel ───────────────────────────────────────────────────


def test_cancel_closes_pr_deletes_ref_and_restores_draft(env: Path, monkeypatch, capsys):
    draft = _draft(env)
    remote = env.parent / "kb-remote"
    pr = {
        "number": 7, "state": "OPEN", "reviewDecision": None,
        "url": _PR_URL, "latestReviews": [],
    }

    def fake_view(repo, *, head):
        return pr

    close_mock = MagicMock()
    _gh(monkeypatch, gh_pr_create=_pr_create, gh_pr_view=fake_view, gh_pr_close=close_mock)
    assert review_cmds.cmd_review_start("x", []) == 0
    capsys.readouterr()

    assert review_cmds.cmd_review_cancel("x") == 0
    close_mock.assert_called_once_with("owner/kb", 7, comment="Review cancelled via Reinicorn.")

    r = run_git(
        "rev-parse", "--verify", f"refs/heads/{_BRANCH}",
        cwd=remote, check=False,
    )
    assert r.returncode != 0  # ref gone from the remote

    text = draft.read_text()
    assert "**Status:** draft" in text
    assert f"**Review-cancelled:** {date.today().isoformat()}" in text
    assert f"**Review-PR:** {_PR_URL}" in text  # gardening trail retained

    assert "review cancelled — x back to draft" in capsys.readouterr().out


def test_restart_after_cancel_clears_cancelled_marker(env: Path, monkeypatch, capsys):
    draft = _draft(env)
    pr = {
        "number": 7, "state": "OPEN", "reviewDecision": None,
        "url": _PR_URL, "latestReviews": [],
    }

    def fake_view(repo, *, head):
        return pr

    _gh(monkeypatch, gh_pr_create=_pr_create, gh_pr_view=fake_view, gh_pr_close=MagicMock())
    assert review_cmds.cmd_review_start("x", []) == 0
    assert review_cmds.cmd_review_cancel("x") == 0
    assert "Review-cancelled" in draft.read_text()

    assert review_cmds.cmd_review_start("x", []) == 0
    text = draft.read_text()
    assert "Review-cancelled" not in text
    assert "**Status:** in-review" in text


# ── status ───────────────────────────────────────────────────


def test_status_zero_open(env: Path, capsys):
    assert review_cmds.cmd_review_status() == 0
    assert "doc reviews: 0 open" in capsys.readouterr().out


def test_status_lists_in_review_draft_with_url(env: Path, capsys):
    d = env / "kb" / "testproject" / "specs" / "drafts"
    d.mkdir(parents=True)
    (d / "x.md").write_text(
        "# x\n"
        "\n"
        "**Date:** 2026-01-01\n"
        "**Author:** tester\n"
        "**Status:** in-review\n"
        f"**Review-PR:** {_PR_URL}\n"
        "\n"
        "body\n"
    )
    assert review_cmds.cmd_review_status() == 0
    out = capsys.readouterr().out
    assert "doc reviews: 1" in out
    assert f"spec/x [in-review] {_PR_URL}" in out


def test_status_counts_plain_drafts_without_open_label(env: Path, capsys):
    """Nonzero header is a bare count — it includes plain drafts, not just reviews."""
    d = env / "kb" / "testproject" / "specs" / "drafts"
    d.mkdir(parents=True)
    (d / "wip.md").write_text("# wip\n\n**Status:** draft\n\nbody\n")
    (d / "hot.md").write_text(
        f"# hot\n\n**Status:** in-review\n**Review-PR:** {_PR_URL}\n\nbody\n"
    )
    assert review_cmds.cmd_review_status() == 0
    out = capsys.readouterr().out
    assert "doc reviews: 2" in out
    assert "open" not in out  # bare count when nonzero, no misleading "open"
    assert "spec/wip [draft]" in out
    assert "spec/hot [in-review]" in out


# ── setup ────────────────────────────────────────────────────


def test_setup_installs_workflow(env, monkeypatch, capsys):
    monkeypatch.setattr(review_cmds.github, "gh_available", lambda: False)
    assert review_cmds.cmd_review_setup() == 0
    wf = env / "kb" / ".github" / "workflows" / "reinicorn-doc-review-cleanup.yml"
    assert wf.is_file()
    assert "rcorn _review-cleanup" in wf.read_text()
    out = capsys.readouterr().out
    assert "ruleset" in out.lower()  # reported as skipped, not silent


def test_setup_substitutes_reinicorn_source_repo(env, monkeypatch):
    """The installed workflow must point at a concrete Reinicorn repo, resolved
    from package metadata — never the raw __REINICORN_REPO__ placeholder."""
    monkeypatch.setattr(review_cmds.github, "gh_available", lambda: False)
    assert review_cmds.cmd_review_setup() == 0
    wf = env / "kb" / ".github" / "workflows" / "reinicorn-doc-review-cleanup.yml"
    assert "__REINICORN_REPO__" not in wf.read_text()


def test_setup_errors_when_source_repo_underivable(env, monkeypatch, capsys):
    monkeypatch.setattr(review_cmds.github, "gh_available", lambda: False)
    monkeypatch.setattr(review_cmds, "reinicorn_source_repo", lambda: None)
    assert review_cmds.cmd_review_setup() == 1
    assert "source repo" in capsys.readouterr().out.lower()


def test_setup_idempotent(env, monkeypatch):
    monkeypatch.setattr(review_cmds.github, "gh_available", lambda: False)
    assert review_cmds.cmd_review_setup() == 0
    assert review_cmds.cmd_review_setup() == 0  # unchanged → success no-op


def test_setup_refuses_clobber_without_force(env, monkeypatch, capsys):
    monkeypatch.setattr(review_cmds.github, "gh_available", lambda: False)
    review_cmds.cmd_review_setup()
    wf = env / "kb" / ".github" / "workflows" / "reinicorn-doc-review-cleanup.yml"
    wf.write_text(wf.read_text() + "# user edit\n")
    assert review_cmds.cmd_review_setup() == 1
    assert review_cmds.cmd_review_setup(force=True) == 0


def test_ruleset_bypasses_every_push_capable_role():
    """The kb is push-first: write, maintain, and admin must all bypass the
    pull_request rule or routine `kb publish` pushes break. GitHub's
    RepositoryRole ids (verified via GraphQL repositoryRoleName):
    2=maintain 4=write 5=admin."""
    actors = review_cmds._RULESET["bypass_actors"]
    assert {a["actor_id"] for a in actors} == {2, 4, 5}
    assert all(a["actor_type"] == "RepositoryRole" for a in actors)
    assert all(a["bypass_mode"] == "always" for a in actors)


def _gh_ok(monkeypatch):
    monkeypatch.setattr(review_cmds.github, "gh_available", lambda: True)
    monkeypatch.setattr(review_cmds.github, "gh_authenticated", lambda: True)
    monkeypatch.setattr(
        review_cmds, "remote_url", lambda _kb: "git@github.com:o/kb.git"
    )


def test_setup_hints_cleanup_secret_when_ruleset_applies(env, monkeypatch, capsys):
    """A protected kb main rejects the CI cleanup's runner-token push — setup
    must tell the operator to create the KB_CLEANUP_TOKEN secret."""
    _gh_ok(monkeypatch)

    def fake_run_gh(*args, **kwargs):
        if "--method" in args:  # POST: create ruleset
            return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    monkeypatch.setattr(review_cmds.github, "run_gh", fake_run_gh)
    assert review_cmds.cmd_review_setup() == 0
    out = capsys.readouterr().out
    assert "ruleset applied" in out
    assert "KB_CLEANUP_TOKEN" in out
    assert "gh secret set KB_CLEANUP_TOKEN --repo o/kb" in out


def _role(actor_id):
    return {"actor_id": actor_id, "actor_type": "RepositoryRole", "bypass_mode": "always"}


def _ruleset_gh(monkeypatch, *, detail, captured=None):
    """Wire run_gh for a ruleset that already exists (id=1).

    list → [{name, id:1}]; detail-fetch → *detail* (dict → JSON, or a
    CompletedProcess for failure paths); PUT → records its body into *captured*
    and succeeds. POST must never happen (the ruleset exists).
    """
    import json as _json
    listing = _json.dumps([{"name": "reinicorn-doc-review", "id": 1}])

    def fake_run_gh(*args, **kwargs):
        if "--method" in args and "PUT" in args:
            if captured is not None:
                captured["body"] = _json.loads(kwargs["input_text"])
            return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")
        assert "POST" not in args, "must not POST a duplicate ruleset"
        if args[:2] == ("api", "repos/o/kb/rulesets/1"):
            if isinstance(detail, subprocess.CompletedProcess):
                return detail
            return subprocess.CompletedProcess(args, 0, stdout=_json.dumps(detail), stderr="")
        return subprocess.CompletedProcess(args, 0, stdout=listing, stderr="")

    monkeypatch.setattr(review_cmds.github, "run_gh", fake_run_gh)


def test_setup_detects_existing_ruleset(env, monkeypatch, capsys):
    """A compliant same-named ruleset (required roles present, extra user actor
    and all) is a no-op — report it installed and still surface the secret hint,
    without a PUT."""
    _gh_ok(monkeypatch)
    _ruleset_gh(monkeypatch, detail={
        "name": "reinicorn-doc-review", "target": "branch", "enforcement": "active",
        "bypass_actors": [_role(5), _role(4), _role(2),
                          {"actor_id": 99, "actor_type": "Team", "bypass_mode": "always"}],
    })
    assert review_cmds.cmd_review_setup() == 0
    out = capsys.readouterr().out
    assert "already installed" in out
    assert "KB_CLEANUP_TOKEN" in out


def test_setup_detects_outdated_ruleset_without_force(env, monkeypatch, capsys):
    """A same-named ruleset missing the maintain-role bypass ({4,5} only) is
    drift — without --force, warn and direct to --force, never mutate."""
    _gh_ok(monkeypatch)
    _ruleset_gh(monkeypatch, detail={
        "name": "reinicorn-doc-review", "target": "branch", "enforcement": "active",
        "bypass_actors": [_role(5), _role(4)],
    })
    assert review_cmds.cmd_review_setup() == 0
    out = capsys.readouterr().out
    assert "outdated" in out
    assert "rcorn review setup --force" in out
    assert "KB_CLEANUP_TOKEN" in out  # still active → secret hint stands


def test_setup_force_repairs_outdated_ruleset(env, monkeypatch, capsys):
    """--force merges the missing maintain role into the installed set without
    dropping unrelated user-added actors."""
    _gh_ok(monkeypatch)
    captured = {}
    _ruleset_gh(monkeypatch, captured=captured, detail={
        "name": "reinicorn-doc-review", "target": "branch", "enforcement": "active",
        "bypass_actors": [_role(5), _role(4),
                          {"actor_id": 99, "actor_type": "Team", "bypass_mode": "always"}],
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [{"type": "pull_request", "parameters": {"custom": True}}],
    })
    assert review_cmds.cmd_review_setup(force=True) == 0
    out = capsys.readouterr().out
    assert "ruleset updated" in out
    roles = {a["actor_id"] for a in captured["body"]["bypass_actors"]}
    assert roles == {2, 4, 5, 99}  # required merged in, user Team preserved
    # user-customized rules/conditions round-trip untouched
    assert captured["body"]["rules"] == [{"type": "pull_request", "parameters": {"custom": True}}]


def test_setup_force_replaces_mismatched_bypass_mode(env, monkeypatch, capsys):
    """An existing bypass actor with the same identity but wrong bypass_mode
    (e.g., pull_request instead of always) is replaced by the canonical required
    entry, not duplicated."""
    _gh_ok(monkeypatch)
    captured = {}
    _ruleset_gh(monkeypatch, captured=captured, detail={
        "name": "reinicorn-doc-review", "target": "branch", "enforcement": "active",
        # admin & write have correct mode; maintain is missing; write appears
        # again with wrong mode to verify identity-based deduplication.
        "bypass_actors": [
            _role(5),  # admin: correct
            # write, but with the wrong mode
            {"actor_id": 4, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"},
            {"actor_id": 99, "actor_type": "Team", "bypass_mode": "always"},  # unrelated
        ],
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [{"type": "pull_request", "parameters": {}}],
    })
    assert review_cmds.cmd_review_setup(force=True) == 0
    out = capsys.readouterr().out
    assert "ruleset updated" in out
    bypass = captured["body"]["bypass_actors"]
    # Extract (actor_id, actor_type, bypass_mode) tuples for required roles
    roles = {
        (a["actor_id"], a["actor_type"], a["bypass_mode"])
        for a in bypass
        if a["actor_type"] == "RepositoryRole"
    }
    # All three required roles present with correct mode "always", no duplicates
    assert roles == {(2, "RepositoryRole", "always"),
                     (4, "RepositoryRole", "always"),
                     (5, "RepositoryRole", "always")}
    # Unrelated Team actor preserved
    assert any(a["actor_id"] == 99 and a["actor_type"] == "Team" for a in bypass)


def test_setup_ruleset_bypass_actors_opaque(env, monkeypatch, capsys):
    """GitHub omits bypass_actors when the token lacks ruleset write access —
    warn with remediation, never assume current, never PUT."""
    _gh_ok(monkeypatch)
    _ruleset_gh(monkeypatch, detail={
        "name": "reinicorn-doc-review", "target": "branch", "enforcement": "active",
    })  # no bypass_actors key
    assert review_cmds.cmd_review_setup() == 0
    out = capsys.readouterr().out
    assert "not visible to this token" in out
    assert "KB_CLEANUP_TOKEN" in out  # active → hint stands


def test_setup_ruleset_detail_unreadable(env, monkeypatch, capsys):
    """A failed detail fetch warns rather than assuming the ruleset is current."""
    _gh_ok(monkeypatch)
    _ruleset_gh(monkeypatch, detail=subprocess.CompletedProcess(
        ("api",), 1, stdout="", stderr="404"))
    assert review_cmds.cmd_review_setup() == 0
    out = capsys.readouterr().out
    assert "could not be read" in out
    assert "settings/rules" in out


def test_setup_ruleset_detail_malformed_json(env, monkeypatch, capsys):
    """A successful detail fetch returning malformed JSON warns rather than
    crashing or assuming the ruleset is current."""
    _gh_ok(monkeypatch)
    _ruleset_gh(monkeypatch, detail=subprocess.CompletedProcess(
        ("api",), 0, stdout="{not valid json", stderr=""))
    assert review_cmds.cmd_review_setup() == 0
    out = capsys.readouterr().out
    assert "unreadable configuration" in out
    assert "settings/rules" in out


def test_setup_ruleset_detail_non_dict_json(env, monkeypatch, capsys):
    """A successful detail fetch returning valid JSON that's not a dict (e.g.,
    a list) warns rather than crashing."""
    _gh_ok(monkeypatch)
    _ruleset_gh(monkeypatch, detail=subprocess.CompletedProcess(
        ("api",), 0, stdout="[1, 2, 3]", stderr=""))
    assert review_cmds.cmd_review_setup() == 0
    out = capsys.readouterr().out
    assert "unreadable configuration" in out
    assert "settings/rules" in out


def test_setup_ruleset_bypass_actors_non_list(env, monkeypatch, capsys):
    """bypass_actors present but not a list (e.g., a dict or string) warns
    rather than crashing."""
    _gh_ok(monkeypatch)
    _ruleset_gh(monkeypatch, detail={
        "name": "reinicorn-doc-review", "target": "branch", "enforcement": "active",
        "bypass_actors": {"not": "a list"},
    })
    assert review_cmds.cmd_review_setup() == 0
    out = capsys.readouterr().out
    assert "unreadable configuration" in out
    assert "settings/rules" in out


def test_setup_ruleset_bypass_actors_list_with_non_dict_entries(env, monkeypatch, capsys):
    """bypass_actors is a list but contains non-dict entries (e.g., strings or
    numbers) warns rather than crashing."""
    _gh_ok(monkeypatch)
    _ruleset_gh(monkeypatch, detail={
        "name": "reinicorn-doc-review", "target": "branch", "enforcement": "active",
        "bypass_actors": [_role(5), "not a dict", 42, _role(4)],
    })
    assert review_cmds.cmd_review_setup() == 0
    out = capsys.readouterr().out
    assert "unreadable configuration" in out
    assert "settings/rules" in out


def test_setup_no_secret_hint_when_ruleset_not_applied(env, monkeypatch, capsys):
    """Unprotected kb main: the runner-token fallback pushes fine, so the
    secret hint would be noise."""
    _gh_ok(monkeypatch)

    def fake_run_gh(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="422")

    monkeypatch.setattr(review_cmds.github, "run_gh", fake_run_gh)
    assert review_cmds.cmd_review_setup() == 0
    out = capsys.readouterr().out
    assert "ruleset not applied" in out
    assert "KB_CLEANUP_TOKEN" not in out


def test_setup_warns_on_solo_repo(env, monkeypatch, capsys):
    """On a solo repo, setup warns up front that the approval gate can only be
    a self-review — so the merge-time prompt is never a surprise."""
    import json
    _gh_ok(monkeypatch)
    solo = json.dumps([{"login": "owner", "permissions": {"push": True}}])

    def fake_run_gh(*args, **kwargs):
        if "collaborators" in args[1]:
            return subprocess.CompletedProcess(args, 0, stdout=solo, stderr="")
        if "--method" in args:  # POST: create ruleset
            return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    monkeypatch.setattr(review_cmds.github, "run_gh", fake_run_gh)
    assert review_cmds.cmd_review_setup() == 0
    out = capsys.readouterr().out
    assert "solo repo" in out


def test_setup_no_solo_warning_when_multiple_collaborators(env, monkeypatch, capsys):
    """A repo with two push-capable collaborators is not solo — no warning."""
    import json
    _gh_ok(monkeypatch)
    team = json.dumps([
        {"login": "owner", "permissions": {"push": True}},
        {"login": "alice", "permissions": {"push": True}},
    ])

    def fake_run_gh(*args, **kwargs):
        if "collaborators" in args[1]:
            return subprocess.CompletedProcess(args, 0, stdout=team, stderr="")
        if "--method" in args:
            return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    monkeypatch.setattr(review_cmds.github, "run_gh", fake_run_gh)
    assert review_cmds.cmd_review_setup() == 0
    assert "solo repo" not in capsys.readouterr().out


# ── error surfacing ──────────────────────────────────────────


def test_runtime_error_surfaces_cleanly(env: Path, monkeypatch, capsys):
    _draft(env)

    def boom(kb_dir, target):
        raise RuntimeError("review ref push failed: rejected")

    monkeypatch.setattr(review_cmds, "push_candidate", boom)
    assert review_cmds.cmd_review_start("x", []) == 1

    captured = capsys.readouterr()
    assert "error: review ref push failed: rejected" in captured.out
    assert "Traceback" not in captured.out + captured.err


def test_merge_refuses_slug_collision(env: Path, monkeypatch, capsys):
    """A doc already occupying the final path on main (status not in-review,
    draft still present) is a slug collision — merge must refuse instead of
    silently deleting the never-reviewed draft."""
    _draft(env)
    kb = env / "kb"
    (kb / "testproject/specs/x.md").write_text("# Old X\n\n**Status:** approved\n")
    run_git("add", "-A", cwd=kb)
    run_git("commit", "-q", "-m", "old landed doc", cwd=kb)
    run_git("push", "-q", "origin", "main", cwd=kb)
    _gh(monkeypatch)

    assert review_cmds.cmd_review_merge("x") == 1
    out = capsys.readouterr().out
    assert "slug collision" in out
    # the unreviewed draft survives on remote main
    assert _remote_show(
        env.parent / "kb-remote", "main", "testproject/specs/drafts/x.md"
    ) is not None


def test_merge_after_ci_cleanup_syncs_local(env: Path, monkeypatch, capsys, tmp_path):
    """Final approved on main and the draft already gone there (CI cleaned up
    after a browser merge) — merge just pulls and reports, no error."""
    _draft(env)
    _gh(monkeypatch, gh_pr_create=_pr_create)
    assert review_cmds.cmd_review_start("x", []) == 0
    # Simulate the merged PR plus CI cleanup, remote-side only.
    remote = env.parent / "kb-remote"
    sim = tmp_path / "sim"
    run_git("clone", "-q", str(remote), str(sim))
    run_git("config", "user.email", "t@t.com", cwd=sim)
    run_git("config", "user.name", "T", cwd=sim)
    final = sim / "testproject/specs/x.md"
    final.write_text(
        (sim / "testproject/specs/drafts/x.md").read_text().replace(
            "**Status:** in-review", "**Status:** approved"
        )
    )
    run_git("rm", "-q", "testproject/specs/drafts/x.md", cwd=sim)
    run_git("add", "-A", cwd=sim)
    run_git("commit", "-q", "-m", "ci cleanup", cwd=sim)
    run_git("push", "-q", "origin", "main", cwd=sim)
    capsys.readouterr()

    assert review_cmds.cmd_review_merge("x") == 0
    out = capsys.readouterr().out
    assert "already landed" in out
    # local kb synced: draft gone, approved doc present
    assert not (env / "kb/testproject/specs/drafts/x.md").exists()
    assert "**Status:** approved" in (env / "kb/testproject/specs/x.md").read_text()


def test_cancel_warns_when_gh_pr_lookup_fails(env: Path, monkeypatch, capsys):
    """gh is up but the PR can't be found — say so instead of silently leaving
    a possibly-open PR behind."""
    _draft(env)
    assert review_cmds.cmd_review_link("x", _PR_URL) == 0
    _gh(monkeypatch, gh_pr_view=lambda _repo, **_kw: None)
    capsys.readouterr()

    assert review_cmds.cmd_review_cancel("x") == 0
    out = capsys.readouterr().out
    assert "no PR found" in out
    assert _PR_URL in out
