"""Tests for individual lint rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from reinicorn.git import run_git
from reinicorn.linter.rules.cross_links import CrossLinksRule
from reinicorn.linter.rules.docs_freshness import DocsFreshnessRule
from reinicorn.linter.rules.draft_refs import DraftRefsRule
from reinicorn.linter.rules.plan_structure import PlanStructureRule


class TestCrossLinks:
    def test_no_broken_links(self, kb_repo: Path):
        (kb_repo / "AGENTS.md").write_text("# Agents\n\nNo links.\n")
        rule = CrossLinksRule()
        assert rule.run(kb_repo) == []

    def test_detects_broken_link(self, kb_repo: Path):
        (kb_repo / "AGENTS.md").write_text(
            "# Agents\n\n[broken](nonexistent.md)\n"
        )
        rule = CrossLinksRule()
        diags = rule.run(kb_repo)
        assert len(diags) >= 1
        assert "nonexistent.md" in diags[0]

    def test_skips_urls(self, kb_repo: Path):
        (kb_repo / "AGENTS.md").write_text(
            "# Agents\n\n[link](https://example.com)\n"
        )
        rule = CrossLinksRule()
        assert rule.run(kb_repo) == []

    def test_skips_anchors(self, kb_repo: Path):
        (kb_repo / "AGENTS.md").write_text(
            "# Agents\n\n[link](#section)\n"
        )
        rule = CrossLinksRule()
        assert rule.run(kb_repo) == []

    def test_skips_links_in_code_fences(self, kb_repo: Path):
        """Links inside fenced code blocks are illustrative, not real references."""
        (kb_repo / "AGENTS.md").write_text(
            "# Agents\n\n```markdown\n[example](does-not-exist.md)\n```\n"
        )
        rule = CrossLinksRule()
        assert rule.run(kb_repo) == []

    def test_detects_broken_link_after_closing_fence(self, kb_repo: Path):
        """Fence tracking must reset so links after a closed fence are still checked."""
        (kb_repo / "AGENTS.md").write_text(
            "# Agents\n\n```\nfenced\n```\n\n[broken](nope.md)\n"
        )
        rule = CrossLinksRule()
        diags = rule.run(kb_repo)
        assert len(diags) >= 1
        assert "nope.md" in diags[0]


class TestDocsFreshness:
    def test_fresh_docs_pass(self, kb_repo: Path):
        # All docs in the fixture are just-created, so they're fresh
        rule = DocsFreshnessRule(max_days=30)
        assert rule.run(kb_repo) == []

    def test_no_key_docs_pass(self, tmp_path: Path):
        rule = DocsFreshnessRule(max_days=1)
        assert rule.run(tmp_path) == []


class TestPlanStructure:
    def test_no_active_plans_pass(self, kb_repo: Path):
        rule = PlanStructureRule()
        assert rule.run(kb_repo) == []

    def test_valid_plan_passes(self, kb_repo: Path):
        plan_dir = kb_repo / "kb" / "testrepo" / "exec-plans" / "active" / "feature-x"
        plan_dir.mkdir(parents=True)
        (plan_dir / "plan.md").write_text(
            "# Plan\n\n**Spec:** N/A\n**Status:** planning\n\n"
            "## Goal\nDo stuff\n\n## Acceptance Criteria\n"
            "- Done\n\n## Tasks\n- [ ] thing\n"
        )

        rule = PlanStructureRule()
        assert rule.run(kb_repo) == []

    def test_missing_sections_detected(self, kb_repo: Path):
        plan_dir = kb_repo / "kb" / "testrepo" / "exec-plans" / "active" / "feature-y"
        plan_dir.mkdir(parents=True)
        (plan_dir / "plan.md").write_text(
            "# Plan\n\n**Spec:** N/A\n**Status:** planning\n\nNo required sections.\n"
        )

        rule = PlanStructureRule()
        diags = rule.run(kb_repo)
        assert len(diags) == 3  # Goal, Acceptance Criteria, Tasks

    def test_missing_spec_field_detected(self, kb_repo: Path):
        plan_dir = kb_repo / "kb" / "testrepo" / "exec-plans" / "active" / "feature-z"
        plan_dir.mkdir(parents=True)
        (plan_dir / "plan.md").write_text(
            "# Plan\n\n**Status:** planning\n\n## Goal\nDo stuff\n\n"
            "## Acceptance Criteria\n- Done\n\n## Tasks\n- [ ] thing\n"
        )

        diags = PlanStructureRule().run(kb_repo)
        assert len(diags) == 1
        assert "Missing '**Spec:**' field" in diags[0]


def _track(repo: Path) -> None:
    """Stage everything so `git ls-files` sees it.

    draft-refs resolves against git, not the filesystem, so a doc only counts
    once it is tracked. Staging is enough — no commit needed.
    """
    run_git("add", "-A", cwd=repo)


class TestDraftRefs:
    def _make_plan(self, kb_repo: Path, branch: str, body: str) -> Path:
        plan_dir = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / branch
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "plan.md"
        plan_file.write_text(body)
        _track(kb_repo)
        return plan_file

    def _make_spec(self, kb_repo: Path, rel: str, status: str | None) -> Path:
        spec = kb_repo / "kb" / "testproject" / rel
        spec.parent.mkdir(parents=True, exist_ok=True)
        header = f"**Status:** {status}\n" if status else ""
        spec.write_text(f"# Doc\n\n{header}\n## Problem\n\nbody\n")
        _track(kb_repo)
        return spec

    @staticmethod
    def _plan(spec_value: str, body: str = "") -> str:
        return f"# Plan\n\n**Spec:** {spec_value}\n**Status:** planning\n\n{body}"

    def test_no_active_plans_pass(self, kb_repo: Path):
        assert DraftRefsRule().run(kb_repo) == []

    # ── the declared Spec field ──────────────────────────────

    def test_missing_spec_field_is_reported(self, kb_repo: Path):
        """Omitting the reference must not be a way to dodge the gate."""
        self._make_plan(kb_repo, "feature-a", "# Plan\n\n**Status:** planning\n")
        diags = DraftRefsRule().run(kb_repo)
        assert len(diags) == 1
        assert "no '**Spec:**' field" in diags[0]

    def test_template_placeholder_is_reported(self, kb_repo: Path):
        self._make_plan(
            kb_repo, "feature-b",
            self._plan("[kb path to the spec this implements, or N/A]"),
        )
        diags = DraftRefsRule().run(kb_repo)
        assert len(diags) == 1
        assert "no '**Spec:**' field" in diags[0]

    def test_not_applicable_is_exempt(self, kb_repo: Path):
        self._make_plan(kb_repo, "feature-c", self._plan("N/A"))
        assert DraftRefsRule().run(kb_repo) == []

    def test_not_applicable_is_case_insensitive(self, kb_repo: Path):
        self._make_plan(kb_repo, "feature-d", self._plan("n/a"))
        assert DraftRefsRule().run(kb_repo) == []

    # ── path styles all resolve to the same doc ──────────────

    @pytest.mark.parametrize("ref", [
        "specs/drafts/wip.md",                    # scope-relative
        "testproject/specs/drafts/wip.md",        # kb-relative
        "kb/testproject/specs/drafts/wip.md",     # kb-prefixed
    ])
    def test_every_path_style_resolves(self, kb_repo: Path, ref: str):
        self._make_spec(kb_repo, "specs/drafts/wip.md", "draft")
        self._make_plan(kb_repo, "feature-e", self._plan(ref))
        diags = DraftRefsRule().run(kb_repo)
        assert len(diags) == 1
        assert "drafts" in diags[0]

    def test_drafts_fallback_catches_future_approved_path(self, kb_repo: Path):
        """The second-order miss: a plan citing the path the spec *will* have."""
        self._make_spec(kb_repo, "specs/drafts/wip.md", "in-review")
        self._make_plan(kb_repo, "feature-f", self._plan("specs/wip.md"))
        diags = DraftRefsRule().run(kb_repo)
        assert len(diags) == 1
        assert "specs/drafts/wip.md" in diags[0]

    def test_approved_wins_over_same_named_draft(self, kb_repo: Path):
        """Exact match first — the fallback must not hijack a real approved ref."""
        self._make_spec(kb_repo, "specs/dual.md", "approved")
        self._make_spec(kb_repo, "specs/drafts/dual.md", "draft")
        self._make_plan(kb_repo, "feature-g", self._plan("specs/dual.md"))
        assert DraftRefsRule().run(kb_repo) == []

    # ── unresolved / ambiguous / untracked ───────────────────

    def test_unresolved_reference_is_reported(self, kb_repo: Path):
        self._make_plan(kb_repo, "feature-h", self._plan("specs/typo.md"))
        diags = DraftRefsRule().run(kb_repo)
        assert len(diags) == 1
        assert "matches no git-tracked kb path" in diags[0]

    def test_untracked_doc_does_not_satisfy_a_reference(self, kb_repo: Path):
        """On disk but never committed is not a real reference."""
        self._make_plan(kb_repo, "feature-i", self._plan("specs/ghost.md"))
        spec = kb_repo / "kb" / "testproject" / "specs" / "ghost.md"
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text("# Ghost\n\n**Status:** approved\n")  # deliberately unstaged
        diags = DraftRefsRule().run(kb_repo)
        assert len(diags) == 1
        assert "matches no git-tracked kb path" in diags[0]

    def test_ambiguous_reference_names_every_candidate(self, kb_repo: Path):
        """'specs/x.md' hitting both kb-relative and scope-relative tracked paths."""
        self._make_spec(kb_repo, "specs/dup.md", "approved")
        top = kb_repo / "kb" / "specs"
        top.mkdir(parents=True, exist_ok=True)
        (top / "dup.md").write_text("# Other\n\n**Status:** approved\n")
        _track(kb_repo)
        self._make_plan(kb_repo, "feature-j", self._plan("specs/dup.md"))
        diags = DraftRefsRule().run(kb_repo)
        assert len(diags) == 1
        assert "ambiguous" in diags[0]
        assert "specs/dup.md" in diags[0]
        assert "testproject/specs/dup.md" in diags[0]

    @pytest.mark.parametrize("ref", [
        "../../../etc/passwd.md",
        "specs/../../../outside.md",
        "/etc/specs/passwd.md",
    ])
    def test_traversal_and_absolute_paths_resolve_to_nothing(
        self, kb_repo: Path, ref: str
    ):
        self._make_plan(kb_repo, "feature-k", self._plan(ref))
        diags = DraftRefsRule().run(kb_repo)
        assert len(diags) == 1
        assert "matches no git-tracked kb path" in diags[0]

    # ── status handling ─────────────────────────────────────

    def test_in_review_doc_reference_is_reported(self, kb_repo: Path):
        self._make_spec(kb_repo, "specs/hot.md", "in-review")
        self._make_plan(kb_repo, "feature-l", self._plan("specs/hot.md"))
        diags = DraftRefsRule().run(kb_repo)
        assert len(diags) == 1
        assert "in-review" in diags[0]

    def test_legacy_doc_without_status_exempt(self, kb_repo: Path):
        self._make_spec(kb_repo, "specs/old.md", None)
        self._make_plan(kb_repo, "feature-m", self._plan("specs/old.md"))
        assert DraftRefsRule().run(kb_repo) == []

    def test_approved_doc_exempt(self, kb_repo: Path):
        self._make_spec(kb_repo, "specs/ok.md", "approved")
        self._make_plan(kb_repo, "feature-n", self._plan("specs/ok.md"))
        assert DraftRefsRule().run(kb_repo) == []

    # ── prose backstop ──────────────────────────────────────

    def test_prose_backstop_catches_draft_under_not_applicable(self, kb_repo: Path):
        """Declaring N/A must not license building on a draft anyway."""
        self._make_spec(kb_repo, "specs/drafts/sneak.md", "draft")
        self._make_plan(
            kb_repo, "feature-o",
            self._plan("N/A", "Really builds on specs/drafts/sneak.md though.\n"),
        )
        diags = DraftRefsRule().run(kb_repo)
        assert len(diags) == 1
        assert "sneak" in diags[0]

    def test_declared_and_prose_reference_reports_once(self, kb_repo: Path):
        """One offending doc is one violation, however many times it is named."""
        self._make_spec(kb_repo, "specs/drafts/dup.md", "draft")
        self._make_plan(
            kb_repo, "feature-p",
            self._plan("specs/drafts/dup.md", "As described in specs/drafts/dup.md.\n"),
        )
        assert len(DraftRefsRule().run(kb_repo)) == 1

    def test_skips_refs_in_code_fences(self, kb_repo: Path):
        """A drafts path shown as an illustrative example in a fence is not a real ref."""
        self._make_spec(kb_repo, "specs/drafts/example.md", "draft")
        self._make_plan(
            kb_repo, "feature-q",
            self._plan("N/A", "```\nspecs/drafts/example.md\n```\n"),
        )
        assert DraftRefsRule().run(kb_repo) == []

    def test_unresolvable_prose_is_ignored(self, kb_repo: Path):
        """Prose is not a contract — only the declared field is held to that."""
        self._make_plan(
            kb_repo, "feature-r",
            self._plan("N/A", "Maybe see specs/nowhere.md sometime.\n"),
        )
        assert DraftRefsRule().run(kb_repo) == []
