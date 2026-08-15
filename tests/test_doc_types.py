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


def test_addressing_values():
    assert REGISTRY["spec"].addressing == "slug"
    assert REGISTRY["prd"].addressing == "slug"
    assert REGISTRY["debt"].addressing == "slug"
    assert REGISTRY["idea"].addressing == "slug"
    assert REGISTRY["plan"].addressing == "branch"
    assert REGISTRY["retro"].addressing == "branch"
    assert REGISTRY["principle"].addressing == "singleton"


def test_title_source_values():
    assert REGISTRY["idea"].title_source == "free_text"
    assert REGISTRY["plan"].title_source == "none"
    assert REGISTRY["retro"].title_source == "none"
    for key in ("spec", "prd", "debt", "principle"):
        assert REGISTRY[key].title_source == "title"


def test_principle_append_mode():
    p = REGISTRY["principle"]
    assert p.create_verb == "add"
    assert p.create_mode == "append"
    assert p.create_status == "active"


def test_create_status_values():
    assert REGISTRY["idea"].create_status == "new"
    assert REGISTRY["plan"].create_status == "planning"
    for key in ("spec", "prd", "debt", "retro"):
        assert REGISTRY[key].create_status == "draft"


def test_debt_extra_meta():
    assert dict(REGISTRY["debt"].extra_meta) == {
        "severity": "medium", "category": "_domain_", "remediation": "planned",
    }
    for key in ("spec", "prd", "idea", "plan", "retro", "principle"):
        assert REGISTRY[key].extra_meta == ()


def test_readme_labels():
    assert REGISTRY["spec"].readme_label == "Approved specs"
    assert REGISTRY["prd"].readme_label == "Product requirements"
    assert REGISTRY["plan"].readme_label == "Active plans"
    assert REGISTRY["debt"].readme_label == "Technical debt"
    assert REGISTRY["principle"].readme_label == "Golden principles"
    assert REGISTRY["idea"].readme_label is None
    assert REGISTRY["retro"].readme_label is None


def test_registry_invariant_required_fields_nonempty():
    for dt in REGISTRY.values():
        assert dt.help_text, dt.key
        assert dt.create_verb, dt.key
        assert dt.create_status, dt.key
        assert dt.create_hint, dt.key


def test_gated_implies_slug_addressing():
    for dt in gated_types():
        assert dt.addressing == "slug"


def test_registry_rejects_gated_non_slug_row():
    from unittest.mock import patch

    import pytest

    from reinicorn.doc_types import _validate_registry
    bad = DocType(
        key="phantom", dir_path="phantoms", filename="active/{branch}/doc.md",
        protected=True, create_hint="rcorn phantom create",
        help_text="Phantom ops", template_body="",
        addressing="branch", gated=True,
    )
    with patch.dict(REGISTRY, {"phantom": bad}), pytest.raises(ValueError, match="phantom"):
        _validate_registry()
