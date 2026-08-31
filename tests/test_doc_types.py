"""Tests for reins.doc_types registry."""

from __future__ import annotations

from pathlib import Path

from reinicorn.doc_types import (
    DRAFTS_DIR_NAME,
    REGISTRY,
    Addressing,
    CreateMode,
    DocType,
    TitleSource,
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
    assert plan.filename == "{stage}/{branch}/plan.md"
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
    assert retro.filename == "retro.md"

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
    assert REGISTRY["spec"].addressing is Addressing.SLUG
    assert REGISTRY["prd"].addressing is Addressing.SLUG
    assert REGISTRY["debt"].addressing is Addressing.SLUG
    assert REGISTRY["idea"].addressing is Addressing.SLUG
    assert REGISTRY["plan"].addressing is Addressing.BRANCH
    assert REGISTRY["retro"].addressing is Addressing.BRANCH
    assert REGISTRY["principle"].addressing is Addressing.SINGLETON


def test_title_source_values():
    assert REGISTRY["idea"].title_source is TitleSource.FREE_TEXT
    assert REGISTRY["plan"].title_source is TitleSource.NONE
    assert REGISTRY["retro"].title_source is TitleSource.NONE
    for key in ("spec", "prd", "debt", "principle"):
        assert REGISTRY[key].title_source is TitleSource.TITLE


def test_create_hint_is_derived_from_verb_and_title_source():
    """create_hint has no hand-maintained literal — it is computed from
    create_verb/title_source, the same facts `skillset.wiring` derives its
    own create-command cell from (spec: the two must never be able to
    disagree, as the hand-written `"<idea>"` vs derived `"<text>"` once did)."""
    assert REGISTRY["spec"].create_hint == 'rcorn spec create "<title>"'
    assert REGISTRY["idea"].create_hint == 'rcorn idea create "<text>"'
    assert REGISTRY["plan"].create_hint == "rcorn plan create"
    assert REGISTRY["principle"].create_hint == 'rcorn principle add "<title>"'


def test_principle_append_mode():
    p = REGISTRY["principle"]
    assert p.create_verb == "add"
    assert p.create_mode is CreateMode.APPEND
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
        assert dt.addressing is Addressing.SLUG


def test_registry_rejects_gated_non_slug_row():
    from unittest.mock import patch

    import pytest

    from reinicorn.doc_types import _validate_rows
    bad = DocType(
        key="phantom", dir_path="phantoms", filename="active/{branch}/doc.md",
        protected=True,
        help_text="Phantom ops", template_body="",
        addressing=Addressing.BRANCH, gated=True,
    )
    with patch.dict(REGISTRY, {"phantom": bad}), pytest.raises(ValueError, match="phantom"):
        _validate_rows(REGISTRY, "test")


def test_plan_precedes_retro_for_shared_dir():
    """Row order is meaningful (see the comment above REGISTRY): plan and
    retro share a dir_path, and by_dir must resolve it to plan."""
    assert REGISTRY["plan"].dir_path == REGISTRY["retro"].dir_path
    keys = list(REGISTRY)
    assert keys.index("plan") < keys.index("retro")
    assert by_dir(REGISTRY["plan"].dir_path) is REGISTRY["plan"]
