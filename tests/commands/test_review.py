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
        review_cmds, "remote_url", lambda kb: "git@github.com:o/kb.git"
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


def test_setup_detects_existing_ruleset(env, monkeypatch, capsys):
    """An already-installed ruleset is not a failure — report it as such (not
    'plan/permissions?') and still surface the secret hint."""
    _gh_ok(monkeypatch)
    listing = '[{"name": "reinicorn-doc-review", "id": 1}]'

    def fake_run_gh(*args, **kwargs):
        assert "--method" not in args, "must not POST a duplicate ruleset"
        return subprocess.CompletedProcess(args, 0, stdout=listing, stderr="")

    monkeypatch.setattr(review_cmds.github, "run_gh", fake_run_gh)
    assert review_cmds.cmd_review_setup() == 0
    out = capsys.readouterr().out
    assert "already installed" in out
    assert "KB_CLEANUP_TOKEN" in out


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
