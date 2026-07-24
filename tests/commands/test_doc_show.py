"""Tests for reinicorn <type> show / list commands (per-type kb doc reading)."""

from __future__ import annotations

import pytest

from reinicorn.commands.doc_show import (
    PREVIEW_CHARS,
    _doc_files,
    cmd_doc_list,
    cmd_doc_show,
    cmd_plan_show,
    cmd_retro_show,
)
from reinicorn.doc_types import DRAFTS_DIR_NAME, REGISTRY


@pytest.fixture(autouse=True)
def _pin_kb_scope(monkeypatch):
    """Pin kb_scope() to "testproject" to match the kb_repo fixture's layout."""
    monkeypatch.setattr("reinicorn.commands.doc_show.kb_scope", lambda _root: "testproject")


def _write_spec(kb_repo, slug, body):
    d = kb_repo / "kb" / "testproject" / "specs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.md").write_text(body)


def test_show_short_doc_prints_all(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    _write_spec(kb_repo, "my-spec", "# My Spec\n\n**Status:** draft\n\nBody.\n")
    assert cmd_doc_show("spec", "my-spec") == 0
    out = capsys.readouterr().out
    assert "# My Spec" in out
    assert "truncated" not in out


def test_show_long_doc_truncates_with_hint(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    _write_spec(kb_repo, "big", "# Big\n\n" + "x" * (PREVIEW_CHARS * 2))
    assert cmd_doc_show("spec", "big") == 0
    out = capsys.readouterr().out
    assert "… (truncated," in out
    assert "chars total)" in out
    assert "next: rcorn spec show big --full" in out
    assert len(out) < PREVIEW_CHARS * 2


def test_show_full_flag_prints_everything(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    body = "# Big\n\n" + "x" * (PREVIEW_CHARS * 2)
    _write_spec(kb_repo, "big", body)
    assert cmd_doc_show("spec", "big", full=True) == 0
    out = capsys.readouterr().out
    assert "truncated" not in out
    assert "x" * (PREVIEW_CHARS * 2) in out


def test_show_unknown_slug_lists_valid_slugs(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    _write_spec(kb_repo, "real-spec", "# Real\n")
    assert cmd_doc_show("spec", "nope") == 1
    out = capsys.readouterr().out
    assert "error: no spec named 'nope'" in out
    assert "real-spec" in out


def test_list_shows_count_slug_title_status(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    _write_spec(kb_repo, "a-spec", "# Alpha Spec\n\n**Status:** approved\n")
    assert cmd_doc_list("spec") == 0
    out = capsys.readouterr().out
    assert "specs: 1 total" in out
    assert "a-spec — Alpha Spec [approved]" in out
    assert "next: rcorn spec show <slug>" in out


def test_list_empty_is_definitive(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    assert cmd_doc_list("spec") == 0
    out = capsys.readouterr().out
    assert "specs: 0 found" in out
    assert 'next: rcorn spec create "<title>"' in out


def test_plan_show_defaults_to_current_branch(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    plan_dir = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "main"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text("# Execution Plan: main\n\n## Goal\nShip.\n")
    assert cmd_plan_show() == 0
    out = capsys.readouterr().out
    assert "# Execution Plan: main" in out


def test_plan_show_missing_current_branch_suggests_create(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    assert cmd_plan_show() == 1
    out = capsys.readouterr().out
    assert "error: no plan for branch 'main'" in out
    assert "next: rcorn plan create" in out


def test_plan_show_missing_other_branch_lists_branches(kb_repo, monkeypatch, capsys):
    """plan create only works on the current branch — for any other branch,
    point at branches that do have a plan instead of a dead-end hint."""
    monkeypatch.chdir(kb_repo)
    plan_dir = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-y"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text("# Execution Plan: feature-y\n")
    assert cmd_plan_show("no-such-branch") == 1
    out = capsys.readouterr().out
    assert "error: no plan for branch 'no-such-branch'" in out
    assert "rcorn plan create" not in out
    assert "feature-y" in out


def test_plan_show_missing_other_branch_no_plans_is_definitive(
    kb_repo, monkeypatch, capsys,
):
    monkeypatch.chdir(kb_repo)
    assert cmd_plan_show("no-such-branch") == 1
    out = capsys.readouterr().out
    assert "rcorn plan create" not in out
    assert "plans: 0 found" in out


def test_list_debt_skips_index(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    debt_dir = kb_repo / "kb" / "testproject" / "tech-debt"
    debt_dir.mkdir(parents=True, exist_ok=True)
    (debt_dir / "some-debt.md").write_text(
        "# Some Debt\n\n**Status:** open\n"
    )
    (debt_dir / "index.md").write_text("# Tech Debt Index\n")
    assert cmd_doc_list("debt") == 0
    out = capsys.readouterr().out
    assert "debts: 1 total" in out
    assert "some-debt" in out
    assert "index" not in out


def test_show_idea_globs_username_subdirs(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    idea_dir = kb_repo / "kb" / "testproject" / "ideas" / "alice"
    idea_dir.mkdir(parents=True, exist_ok=True)
    (idea_dir / "dark-mode.md").write_text("# Dark Mode\n\nAdd a dark theme.\n")
    assert cmd_doc_show("idea", "dark-mode") == 0
    out = capsys.readouterr().out
    assert "# Dark Mode" in out
    assert "Add a dark theme." in out


def test_retro_show_defaults_to_current_branch(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    retro_dir = kb_repo / "kb" / "testproject" / "exec-plans" / "completed" / "main"
    retro_dir.mkdir(parents=True, exist_ok=True)
    (retro_dir / "retro.md").write_text("# Retro: main\n\n## What Went Well\n- TDD\n")
    assert cmd_retro_show() == 0
    out = capsys.readouterr().out
    assert "# Retro: main" in out


def test_retro_show_prefers_active_dir(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    exec_plans = kb_repo / "kb" / "testproject" / "exec-plans"
    active_dir = exec_plans / "active" / "main"
    active_dir.mkdir(parents=True, exist_ok=True)
    (active_dir / "retro.md").write_text("# Retro: active main\n\n## What Went Well\n- Active\n")
    # A completed copy also exists; the active one must win.
    completed_dir = exec_plans / "completed" / "main"
    completed_dir.mkdir(parents=True, exist_ok=True)
    (completed_dir / "retro.md").write_text("# Retro: completed main\n\n## Well\n- Old\n")
    assert cmd_retro_show() == 0
    out = capsys.readouterr().out
    assert "# Retro: active main" in out
    assert "completed main" not in out


def test_retro_show_missing_current_branch_suggests_create(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    assert cmd_retro_show() == 1
    out = capsys.readouterr().out
    assert "error: no retro for branch 'main'" in out
    assert "next: rcorn retro create" in out


def test_retro_show_missing_other_branch_lists_branches(kb_repo, monkeypatch, capsys):
    """retro create only works on the current branch — for any other branch,
    list branches with a retro (completed and active) instead."""
    monkeypatch.chdir(kb_repo)
    exec_plans = kb_repo / "kb" / "testproject" / "exec-plans"
    completed = exec_plans / "completed" / "feature-x"
    completed.mkdir(parents=True, exist_ok=True)
    (completed / "retro.md").write_text("# Retro: feature-x\n")
    active = exec_plans / "active" / "feature-z"
    active.mkdir(parents=True, exist_ok=True)
    (active / "retro.md").write_text("# Retro: feature-z\n")
    assert cmd_retro_show("ghost") == 1
    out = capsys.readouterr().out
    assert "error: no retro for branch 'ghost'" in out
    assert "rcorn retro create" not in out
    assert "feature-x" in out
    assert "feature-z" in out


def test_retro_show_missing_other_branch_no_retros_is_definitive(
    kb_repo, monkeypatch, capsys,
):
    monkeypatch.chdir(kb_repo)
    assert cmd_retro_show("ghost") == 1
    out = capsys.readouterr().out
    assert "rcorn retro create" not in out
    assert "retros: 0 found" in out


def test_list_excludes_drafts_by_default(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    _write_spec(kb_repo, "landed", "# Landed\n\n**Status:** approved\n\n## Problem\n\nx\n")
    drafts_dir = kb_repo / "kb" / "testproject" / "specs" / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    (drafts_dir / "wip.md").write_text(
        "# Wip\n\n**Status:** draft\n\n## Problem\n\nx\n"
    )
    assert cmd_doc_list("spec") == 0
    out = capsys.readouterr().out
    assert "landed" in out
    assert "wip" not in out


def test_list_include_drafts_marks_them(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    drafts_dir = kb_repo / "kb" / "testproject" / "specs" / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    (drafts_dir / "wip.md").write_text(
        "# Wip\n\n**Status:** draft\n\n## Problem\n\nx\n"
    )
    assert cmd_doc_list("spec", include_drafts=True) == 0
    out = capsys.readouterr().out
    assert "wip" in out
    assert "[DRAFT]" in out


def test_show_finds_draft_only_with_flag(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    drafts_dir = kb_repo / "kb" / "testproject" / "specs" / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    (drafts_dir / "wip.md").write_text(
        "# Wip\n\n**Status:** draft\n\n## Problem\n\nx\n"
    )
    assert cmd_doc_show("spec", "wip") == 1
    assert cmd_doc_show("spec", "wip", include_drafts=True) == 0


def test_show_miss_hints_include_drafts_only_when_draft_exists(
    kb_repo, monkeypatch, capsys,
):
    monkeypatch.chdir(kb_repo)
    drafts_dir = kb_repo / "kb" / "testproject" / "specs" / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    (drafts_dir / "wip.md").write_text(
        "# Wip\n\n**Status:** draft\n\n## Problem\n\nx\n"
    )
    # Slug that only exists as a draft: point at the flag.
    assert cmd_doc_show("spec", "wip") == 1
    out = capsys.readouterr().out
    assert "--include-drafts" in out
    assert "draft" in out
    # Slug that exists nowhere: no misleading hint.
    assert cmd_doc_show("spec", "nope") == 1
    out = capsys.readouterr().out
    assert "--include-drafts" not in out


@pytest.mark.parametrize(
    "key",
    [k for k, dt in REGISTRY.items() if "{branch}" not in dt.filename],
)
def test_default_never_leaks_drafts_regardless_of_glob_shape(kb_repo, key):
    """Structural guard: drafts exclusion must not depend on glob shape.

    Some filename patterns descend into subdirectories (idea's */*.md), so
    a drafts/ file can match the default glob. Plant leak files at every
    depth under drafts/ that could match and assert the default listing
    never returns a path inside the drafts annex — for every current and
    future slug-addressed type, gated or not.
    """
    dt = REGISTRY[key]
    drafts = kb_repo / "kb" / "testproject" / dt.dir_path / DRAFTS_DIR_NAME
    (drafts / "sub").mkdir(parents=True, exist_ok=True)
    (drafts / "leak.md").write_text("# Leak\n")
    (drafts / "sub" / "leak.md").write_text("# Leak\n")
    repo_dir = kb_repo / "kb" / "testproject"
    for f in _doc_files(key, repo_dir, include_drafts=False):
        assert DRAFTS_DIR_NAME not in f.parts, f"{key} leaked draft {f}"
