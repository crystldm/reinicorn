"""Tests for reins.doc_types registry."""

from __future__ import annotations

from pathlib import Path

from reinicorn.doc_types import (
    DRAFTS_DIR_NAME,
    REGISTRY,
    DocType,
    by_dir,
    drafts_dir,
    gated_types,
    get_doc_dir,
    get_protected_map,
)


def test_registry_contains_all_doc_types():
    expected_keys = {"spec", "plan", "prd", "debt", "idea", "retro", "principle"}
    assert set(REGISTRY.keys()) == expected_keys


def test_doc_type_is_frozen_dataclass():
    dt = REGISTRY["spec"]
    assert isinstance(dt, DocType)
    assert dt.key == "spec"
    assert dt.dir_path == "specs"
    assert dt.protected is True


def test_get_doc_dir(tmp_path):
    result = get_doc_dir("spec", tmp_path)
    assert result == tmp_path / "specs"


def test_get_doc_dir_unknown_key(tmp_path):
    import pytest
    with pytest.raises(KeyError):
        get_doc_dir("nonexistent", tmp_path)


def test_get_protected_map():
    pmap = get_protected_map()
    assert pmap["specs"] == "spec"
    assert pmap["prds"] == "prd"
    assert pmap["tech-debt"] == "debt"
    assert pmap["ideas"] == "idea"
    # principle uses "." so it's not in the protected map
    assert "." not in pmap


def test_by_dir_found():
    dt = by_dir("specs")
    assert dt is not None
    assert dt.key == "spec"


def test_by_dir_not_found():
    assert by_dir("nonexistent") is None


def test_registry_entries_match_spec_table():
    """Verify specific registry values match the spec table."""
    plan = REGISTRY["plan"]
    assert plan.dir_path == "exec-plans"
    assert plan.filename == "active/{branch}/plan.md"
    assert plan.protected is True
    assert "Goal" in plan.required_sections
    assert "Acceptance Criteria" in plan.required_sections
    assert "Tasks" in plan.required_sections

    prd = REGISTRY["prd"]
    assert prd.dir_path == "prds"
    assert prd.index_file == "index.md"
    assert "User Stories" in prd.required_sections

    spec = REGISTRY["spec"]
    assert spec.dir_path == "specs"
    assert spec.index_file == "index.md"
    assert "Design" in spec.required_sections

    debt = REGISTRY["debt"]
    assert debt.dir_path == "tech-debt"
    assert debt.filename == "{slug}.md"

    retro = REGISTRY["retro"]
    assert retro.dir_path == "exec-plans"
    assert retro.filename == "completed/{branch}/retro.md"

    principle = REGISTRY["principle"]
    assert principle.dir_path == "."
    assert principle.protected is False


def test_spec_is_gated():
    assert REGISTRY["spec"].gated is True


def test_only_spec_gated_in_v1():
    assert [dt.key for dt in gated_types()] == ["spec"]


def test_gated_defaults_false():
    assert REGISTRY["plan"].gated is False
    assert REGISTRY["idea"].gated is False


def test_drafts_dir_under_type_dir():
    repo_dir = Path("/kb/myrepo")
    assert drafts_dir("spec", repo_dir) == repo_dir / "specs" / DRAFTS_DIR_NAME
