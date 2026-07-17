"""Tests for individual lint rules."""

from __future__ import annotations

from pathlib import Path

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
            "# Plan\n\n## Goal\nDo stuff\n\n## Acceptance Criteria\n"
            "- Done\n\n## Tasks\n- [ ] thing\n"
        )

        rule = PlanStructureRule()
        assert rule.run(kb_repo) == []

    def test_missing_sections_detected(self, kb_repo: Path):
        plan_dir = kb_repo / "kb" / "testrepo" / "exec-plans" / "active" / "feature-y"
        plan_dir.mkdir(parents=True)
        (plan_dir / "plan.md").write_text("# Plan\n\nNo required sections.\n")

        rule = PlanStructureRule()
        diags = rule.run(kb_repo)
        assert len(diags) == 3  # Goal, Acceptance Criteria, Tasks


class TestDraftRefs:
    def _make_plan(self, kb_repo: Path, branch: str, body: str) -> Path:
        plan_dir = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / branch
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "plan.md"
        plan_file.write_text(body)
        return plan_file

    def test_no_active_plans_pass(self, kb_repo: Path):
        rule = DraftRefsRule()
        assert rule.run(kb_repo) == []

    def test_flags_drafts_path_reference(self, kb_repo: Path):
        self._make_plan(
            kb_repo, "feature-a",
            "# Plan\n\nBuilds on kb/testproject/specs/drafts/wip.md.\n",
        )
        rule = DraftRefsRule()
        diags = rule.run(kb_repo)
        assert len(diags) == 1
        assert "drafts" in diags[0]

    def test_flags_in_review_doc_reference(self, kb_repo: Path):
        spec = kb_repo / "kb" / "testproject" / "specs"
        spec.mkdir(parents=True)
        (spec / "hot.md").write_text("# Hot\n\n**Status:** in-review\n\n## Problem\n\nbody\n")
        self._make_plan(
            kb_repo, "feature-b",
            "# Plan\n\nBuilds on kb/testproject/specs/hot.md.\n",
        )
        rule = DraftRefsRule()
        diags = rule.run(kb_repo)
        assert len(diags) == 1
        assert "in-review" in diags[0]

    def test_legacy_doc_without_status_exempt(self, kb_repo: Path):
        spec = kb_repo / "kb" / "testproject" / "specs"
        spec.mkdir(parents=True)
        (spec / "old.md").write_text("# Old\n\nNo status field here.\n")
        self._make_plan(
            kb_repo, "feature-c",
            "# Plan\n\nBuilds on kb/testproject/specs/old.md.\n",
        )
        rule = DraftRefsRule()
        assert rule.run(kb_repo) == []

    def test_approved_doc_exempt(self, kb_repo: Path):
        spec = kb_repo / "kb" / "testproject" / "specs"
        spec.mkdir(parents=True)
        (spec / "approved.md").write_text(
            "# Approved\n\n**Status:** approved\n\n## Problem\n\nbody\n"
        )
        self._make_plan(
            kb_repo, "feature-d",
            "# Plan\n\nBuilds on kb/testproject/specs/approved.md.\n",
        )
        rule = DraftRefsRule()
        assert rule.run(kb_repo) == []

    def test_skips_refs_in_code_fences(self, kb_repo: Path):
        """A drafts path shown as an illustrative example in a fence is not a real ref."""
        self._make_plan(
            kb_repo, "feature-e",
            "# Plan\n\n```\nkb/testproject/specs/drafts/example.md\n```\n",
        )
        rule = DraftRefsRule()
        assert rule.run(kb_repo) == []

    def test_ignores_lookalike_dirs_containing_kb(self, kb_repo: Path):
        """'notkb/…' must not match the kb-path regex from its embedded 'kb/'."""
        self._make_plan(
            kb_repo, "feature-f",
            "# Plan\n\nSee notkb/testproject/specs/drafts/wip.md for contrast.\n",
        )
        rule = DraftRefsRule()
        assert rule.run(kb_repo) == []
