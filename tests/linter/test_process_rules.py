"""The stage-3 lint rules read the relation graph, not type names:
``kb/required-sections`` (authoring scope), ``kb/closer-filled`` and
``kb/lifecycle`` (spec: process-as-config §3), plus the config alias the
rename of the structure rule keeps alive.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from reinicorn.git import run_git
from reinicorn.linter.rules.closer_filled import CloserFilledRule
from reinicorn.linter.rules.doc_structure import DocStructureRule
from reinicorn.linter.rules.lifecycle import LifecycleRule, MergeProbe
from reinicorn.linter.runner import run_lints
from tests.conftest import doc_text

REQUIRED_CLOSER = (
    "doc_types:\n"
    "  retro:\n"
    "    closes: {type: plan, required: true}\n"
)
PLAN_BODY = (
    "\n# Plan\n\n## Goal\n\n- Do it.\n\n## Acceptance Criteria\n\n- Done.\n\n"
    "## Tasks\n\n- [ ] one\n"
)
RETRO_BODY = (
    "\n# Retro\n\n## What Went Well\n\n- Shipped.\n\n"
    "## What Could Be Improved\n\n- Tests earlier.\n\n"
    "## Lessons Learned\n\n- Write it down.\n\n## Action Items\n\n- None.\n"
)


def _plan(root: Path, name: str, branch: str, scope: str = "testproject", **meta) -> Path:
    active = root / "kb" / scope / "exec-plans" / "active" / name
    active.mkdir(parents=True, exist_ok=True)
    fields = {
        "type": "plan", "title": "Plan", "slug": name, "status": "in-progress",
        "branch": branch, "spec": "N/A",
    }
    fields.update(meta)
    (active / "plan.md").write_text(doc_text(body=PLAN_BODY, **fields))
    return active


def _retro(active: Path, body: str = RETRO_BODY) -> None:
    (active / "retro.md").write_text(doc_text(
        type="retro", title="Retro", slug=active.name, status="draft",
        branch=active.name, body=body,
    ))


# --- kb/required-sections -----------------------------------------------------


class TestRequiredSections:
    def test_name(self):
        assert DocStructureRule().name() == "kb/required-sections"

    def test_closer_in_active_dir_is_checked(self, kb_repo: Path):
        active = _plan(kb_repo, "feature-a", "feature/a")
        _retro(active, body="\n# Retro\n\n## What Went Well\n\n- ok\n")

        diags = DocStructureRule().run(kb_repo)
        joined = "\n".join(diags)
        assert "feature-a/retro.md" in joined
        assert "'## Lessons Learned' section" in joined
        assert "plan.md" not in joined

    def test_slug_addressed_draft_is_checked(self, kb_repo: Path):
        drafts = kb_repo / "kb" / "testproject" / "specs" / "drafts"
        drafts.mkdir(parents=True)
        (drafts / "thin.md").write_text(doc_text(
            slug="thin", body="\n# Thin\n\n## Problem\n\n- x\n",
        ))

        diags = DocStructureRule().run(kb_repo)
        assert any("drafts/thin.md" in d and "'## Design' section" in d for d in diags)

    def test_approved_gated_doc_is_exempt(self, kb_repo: Path):
        specs = kb_repo / "kb" / "testproject" / "specs"
        specs.mkdir(parents=True)
        (specs / "legacy.md").write_text(doc_text(
            slug="legacy", status="Approved", body="\n# Legacy\n\nprose only\n",
        ))

        assert DocStructureRule().run(kb_repo) == []

    def test_closed_lifecycle_is_exempt(self, kb_repo: Path):
        from reinicorn import frontmatter

        specs = kb_repo / "kb" / "testproject" / "specs"
        specs.mkdir(parents=True)
        (specs / "done.md").write_text(doc_text(
            slug="done", status="implemented",
            lifecycle=frontmatter.LIFECYCLE_DONE, body="\n# Done\n\nprose\n",
        ))

        assert DocStructureRule().run(kb_repo) == []

    def test_completed_stage_is_exempt(self, kb_repo: Path):
        completed = kb_repo / "kb" / "testproject" / "exec-plans" / "completed" / "old"
        completed.mkdir(parents=True)
        (completed / "plan.md").write_text(doc_text(
            type="plan", title="Old", slug="old", status="complete",
            branch="old", spec="N/A", body="\n# Old\n\nno sections\n",
        ))
        (completed / "retro.md").write_text(doc_text(
            type="retro", title="Retro", slug="old", status="draft",
            branch="old", body="\n# Retro\n\nno sections either\n",
        ))

        assert DocStructureRule().run(kb_repo) == []

    def test_runner_accepts_the_old_name_as_alias(self, kb_repo: Path, capsys):
        _plan(kb_repo, "feature-b", "feature/b")
        (kb_repo / "linters" / ".lint-config.json").write_text(json.dumps({
            "rules": {"kb/plan-structure": {"enabled": True, "severity": "error"}},
        }))

        assert run_lints(kb_repo) == 0
        out = capsys.readouterr().out
        assert "[NOTE] rule 'kb/plan-structure' is now 'kb/required-sections'" in out
        assert "[PASS] kb/required-sections" in out
        assert "Total rules run: 1" in out

    def test_alias_does_not_double_run_when_both_configured(self, kb_repo: Path, capsys):
        (kb_repo / "linters" / ".lint-config.json").write_text(json.dumps({
            "rules": {
                "kb/plan-structure": {"enabled": True, "severity": "error"},
                "kb/required-sections": {"enabled": True, "severity": "error"},
            },
        }))

        assert run_lints(kb_repo) == 0
        assert "Total rules run: 1" in capsys.readouterr().out


# --- kb/closer-filled --------------------------------------------------------


class TestCloserFilled:
    def test_defaults_require_nothing(self, kb_repo: Path):
        _plan(kb_repo, "feature-c", "feature/c")
        assert CloserFilledRule().run(kb_repo) == []

    @pytest.fixture
    def required(self, kb_repo: Path) -> Path:
        with (kb_repo / ".reinicorn-config").open("a") as f:
            f.write('REINICORN_KB_SCOPE="testproject"\n')
        (kb_repo / "kb" / "testproject" / "doc-types.yaml").write_text(REQUIRED_CLOSER)
        return kb_repo

    def test_missing_required_closer_is_an_error(self, required: Path):
        _plan(required, "feature-d", "feature/d")

        diags = CloserFilledRule().run(required)
        assert len(diags) == 1
        assert diags[0].startswith("kb/testproject/exec-plans/active/feature-d/plan.md:1")
        assert "retro.md is missing" in diags[0]
        assert "rcorn retro create" in diags[0]

    def test_placeholder_closer_is_an_error(self, required: Path):
        active = _plan(required, "feature-e", "feature/e")
        _retro(active, body="\n# Retro\n\n## What Went Well\n\n- \n")

        diags = CloserFilledRule().run(required)
        assert len(diags) == 1
        assert "only placeholder sections" in diags[0]

    def test_filled_closer_passes(self, required: Path):
        active = _plan(required, "feature-f", "feature/f")
        _retro(active)
        assert CloserFilledRule().run(required) == []

    def test_completed_stage_is_not_judged(self, required: Path):
        completed = required / "kb" / "testproject" / "exec-plans" / "completed" / "old"
        completed.mkdir(parents=True)
        (completed / "plan.md").write_text("# Old\n")
        assert CloserFilledRule().run(required) == []


# --- kb/lifecycle ------------------------------------------------------------


def _commit_all(repo: Path, msg: str) -> None:
    run_git("add", "-A", cwd=repo)
    run_git("commit", "-q", "--allow-empty", "-m", msg, cwd=repo)


@pytest.fixture
def published_repo(kb_repo: Path, tmp_path: Path) -> Path:
    """kb_repo with a bare origin holding main, origin/HEAD resolved."""
    bare = tmp_path / "origin.git"
    run_git("init", "-q", "--bare", "-b", "main", str(bare))
    run_git("remote", "add", "origin", str(bare), cwd=kb_repo)
    run_git("push", "-q", "-u", "origin", "main", cwd=kb_repo)
    run_git("remote", "set-head", "origin", "main", cwd=kb_repo)
    return kb_repo


def _branch(repo: Path, name: str, *, push: bool = True) -> None:
    run_git("checkout", "-q", "-b", name, cwd=repo)
    _commit_all(repo, f"work on {name}")
    if push:
        run_git("push", "-q", "-u", "origin", name, cwd=repo)
    run_git("checkout", "-q", "main", cwd=repo)


def _lifecycle(root: Path) -> list[str]:
    with patch("reinicorn.linter.rules.lifecycle.kb_scope", return_value="testproject"), \
         patch.object(MergeProbe, "pr_heads", return_value=None):
        return LifecycleRule().run(root)


class TestLifecycle:
    def test_no_active_docs_asks_nothing(self, kb_repo: Path):
        with patch.object(MergeProbe, "live_heads") as probe:
            assert _lifecycle(kb_repo) == []
        probe.assert_not_called()

    def test_open_published_branch_stays_active(self, published_repo: Path):
        _branch(published_repo, "feature/open")
        _plan(published_repo, "feature-open", "feature/open")
        assert _lifecycle(published_repo) == []

    def test_never_pushed_branch_stays_active(self, published_repo: Path):
        _branch(published_repo, "feature/local", push=False)
        _plan(published_repo, "feature-local", "feature/local")
        assert _lifecycle(published_repo) == []

    def test_merge_commit_into_default_is_stale(self, published_repo: Path):
        _branch(published_repo, "feature/merged")
        run_git("merge", "-q", "--no-ff", "-m", "merge", "feature/merged", cwd=published_repo)
        run_git("push", "-q", "origin", "main", cwd=published_repo)
        _plan(published_repo, "feature-merged", "feature/merged")

        diags = _lifecycle(published_repo)
        assert len(diags) == 1
        assert diags[0].startswith(
            "kb/testproject/exec-plans/active/feature-merged/plan.md:1"
        )
        assert "merged/deleted but still active" in diags[0]
        assert diags[0].endswith("rcorn plan complete feature/merged")

    def test_published_then_deleted_branch_is_stale(self, published_repo: Path, tmp_path: Path):
        _branch(published_repo, "feature/gone")
        # Deleted on origin by someone else (GitHub's delete-on-merge); the
        # unpruned local tracking ref is the publication evidence.
        run_git("branch", "-D", "feature/gone", cwd=tmp_path / "origin.git")
        _plan(published_repo, "feature-gone", "feature/gone")

        diags = _lifecycle(published_repo)
        assert len(diags) == 1
        assert "feature/gone" in diags[0]

    def test_pruned_deletion_without_pr_evidence_stays_active(self, published_repo: Path):
        _branch(published_repo, "feature/pruned")
        run_git("push", "-q", "origin", "--delete", "feature/pruned", cwd=published_repo)
        run_git("fetch", "-q", "--prune", "origin", cwd=published_repo)
        _plan(published_repo, "feature-pruned", "feature/pruned")

        assert _lifecycle(published_repo) == []

    def test_squash_merge_is_found_through_the_merged_pr(self, published_repo: Path):
        _branch(published_repo, "feature/squashed")  # retained on origin, not an ancestor
        _plan(published_repo, "feature-squashed", "feature/squashed")

        with patch("reinicorn.linter.rules.lifecycle.kb_scope", return_value="testproject"), \
             patch.object(MergeProbe, "pr_heads", return_value={"feature/squashed"}):
            diags = LifecycleRule().run(published_repo)
        assert len(diags) == 1
        assert "feature/squashed" in diags[0]

    def test_no_remote_is_cannot_verify(self, kb_repo: Path):
        _branch(kb_repo, "feature/offline", push=False)
        _plan(kb_repo, "feature-offline", "feature/offline")
        assert _lifecycle(kb_repo) == []

    def test_other_scope_is_not_judged(self, published_repo: Path):
        _branch(published_repo, "feature/theirs")
        run_git("merge", "-q", "--no-ff", "-m", "merge", "feature/theirs", cwd=published_repo)
        run_git("push", "-q", "origin", "main", cwd=published_repo)
        _plan(published_repo, "feature-theirs", "feature/theirs", scope="otherproject")

        assert _lifecycle(published_repo) == []

    def test_network_facts_are_fetched_once_per_run(self, published_repo: Path):
        for i in range(3):
            _branch(published_repo, f"feature/n{i}", push=False)
            _plan(published_repo, f"feature-n{i}", f"feature/n{i}")

        with patch("reinicorn.linter.rules.lifecycle.kb_scope", return_value="testproject"), \
             patch.object(MergeProbe, "_ls_remote_heads", return_value=set()) as ls, \
             patch("reinicorn.linter.rules.lifecycle.gh_pr_heads", return_value=None) as gh, \
             patch("reinicorn.linter.rules.lifecycle.gh_repo_from_url", return_value="o/r"):
            LifecycleRule().run(published_repo)
        assert ls.call_count == 1
        # No tracking ref for any of the three, so the PR questions are
        # asked — once per state, not once per branch, and a failed answer
        # is cached as "cannot verify" rather than retried.
        assert sorted(c.kwargs["state"] for c in gh.call_args_list) == ["all", "merged"]
