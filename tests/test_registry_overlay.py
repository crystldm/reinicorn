"""Tests for the doc-type registry overlay (kb/<scope>/doc-types.yaml).

Spec: process-as-config-doc-type-registry-overlay-and-declarative §1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reinicorn.doc_types import (
    REGISTRY,
    Addressing,
    DocTypesError,
    _reset_registry_cache,
    overlay_keys,
    overlay_path,
    overlay_schema,
    registry,
)


def _repo_with_overlay(tmp_path: Path, overlay_yaml: str | None) -> Path:
    """A repo root with a configured scope and an optional overlay file."""
    from reinicorn.git import run_git

    root = tmp_path / "repo"
    scope_dir = root / "kb" / "myscope"
    scope_dir.mkdir(parents=True)
    run_git("init", "-q", "-b", "main", str(root))
    (root / ".reinicorn-config").write_text("REINICORN_KB_SCOPE=myscope\n")
    if overlay_yaml is not None:
        (scope_dir / "doc-types.yaml").write_text(overlay_yaml)
    return root


def test_no_overlay_reproduces_defaults(tmp_path):
    root = _repo_with_overlay(tmp_path, None)
    effective = registry(root)
    assert set(effective) == set(REGISTRY)
    assert effective["spec"].dir_path == "specs"
    assert effective["plan"].required_fields == ("branch",)


def test_override_changes_only_listed_fields(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  retro:\n"
        "    required_sections: [Only Section]\n",
    )
    retro = registry(root)["retro"]
    assert retro.required_sections == ("Only Section",)
    # Everything unlisted keeps the default.
    assert retro.filename == REGISTRY["retro"].filename
    assert retro.protected is REGISTRY["retro"].protected


def test_add_row_with_derived_defaults(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  rfc:\n"
        "    dir_path: rfcs\n"
        "    filename: '{slug}.md'\n"
        "    addressing: slug\n"
        "    required_sections: [Summary, Motivation]\n",
    )
    rfc = registry(root)["rfc"]
    assert rfc.key == "rfc"
    assert rfc.help_text == "rfc doc operations"
    assert rfc.template_body == "{sections}"
    assert rfc.addressing is Addressing.SLUG
    assert rfc.required_sections == ("Summary", "Motivation")
    # Defaults are untouched.
    assert "rfc" not in REGISTRY


def test_add_row_missing_mandatory_key_fails_closed(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n  rfc:\n    dir_path: rfcs\n",
    )
    with pytest.raises(DocTypesError, match=r"rfc.*mandatory"):
        registry(root)


def test_disabled_row_is_dropped(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n  prd:\n    disabled: true\n",
    )
    assert "prd" not in registry(root)
    assert "prd" in REGISTRY


def test_disabled_row_rejects_other_keys(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n  prd:\n    disabled: true\n    dir_path: x\n",
    )
    with pytest.raises(DocTypesError, match="disabled"):
        registry(root)


def test_unknown_row_key_fails_closed_naming_file_and_key(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n  spec:\n    no_such_field: 1\n",
    )
    with pytest.raises(DocTypesError, match="no_such_field") as e:
        registry(root)
    assert str(overlay_path(root)) in str(e.value)


def test_bad_enum_value_fails_closed(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  rfc:\n"
        "    dir_path: rfcs\n"
        "    filename: '{slug}.md'\n"
        "    addressing: sideways\n",
    )
    with pytest.raises(DocTypesError, match="sideways"):
        registry(root)


def test_invalid_yaml_fails_closed(tmp_path):
    root = _repo_with_overlay(tmp_path, "doc_types: [::not yaml\n")
    with pytest.raises(DocTypesError, match="YAML"):
        registry(root)


def test_missing_top_level_mapping_fails_closed(tmp_path):
    root = _repo_with_overlay(tmp_path, "not_doc_types: {}\n")
    with pytest.raises(DocTypesError, match="doc_types"):
        registry(root)


def test_gated_non_slug_overlay_row_fails_closed(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  ghost:\n"
        "    dir_path: ghosts\n"
        "    filename: 'active/{branch}/ghost.md'\n"
        "    addressing: branch\n"
        "    gated: true\n",
    )
    with pytest.raises(DocTypesError, match="gated"):
        registry(root)


def test_filename_placeholders_must_match_addressing(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  ghost:\n"
        "    dir_path: ghosts\n"
        "    filename: '{slug}.md'\n"
        "    addressing: branch\n",
    )
    with pytest.raises(DocTypesError, match="placeholder"):
        registry(root)


def test_branch_addressed_row_gets_branch_auto_added(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  ghost:\n"
        "    dir_path: ghosts\n"
        "    filename: 'active/{branch}/ghost.md'\n"
        "    addressing: branch\n",
    )
    ghost = registry(root)["ghost"]
    assert "branch" in ghost.fields
    assert "branch" in ghost.required_fields


def test_seq_filename_gets_id_auto_added(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  rfc:\n"
        "    dir_path: rfcs\n"
        "    filename: 'RFC-{seq:04}-{slug}.md'\n"
        "    addressing: slug\n",
    )
    assert "id" in registry(root)["rfc"].fields


def test_registry_memoized_per_root(tmp_path):
    root = _repo_with_overlay(tmp_path, None)
    assert registry(root) is registry(root)
    _reset_registry_cache()
    assert set(registry(root)) == set(REGISTRY)


def test_overlay_keys_annotation_source(tmp_path):
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n  retro:\n    required_sections: [X]\n",
    )
    assert overlay_keys(root) == frozenset({"retro"})
    assert overlay_keys(_repo_with_overlay(tmp_path / "b", None)) == frozenset()


def test_overlay_schema_tracks_dataclass_fields():
    schema = overlay_schema()
    row = schema["properties"]["doc_types"]["additionalProperties"]
    assert row["properties"]["disabled"] == {"type": "boolean"}
    assert row["properties"]["addressing"] == {
        "enum": ["slug", "branch", "singleton"]
    }
    assert row["properties"]["required_sections"]["type"] == "array"
    assert "key" not in row["properties"]
    json.dumps(schema)  # must be serializable


def test_frontmatter_vocabulary_reads_overlay(tmp_path, monkeypatch):
    """A custom type's declared fields validate through frontmatter."""
    root = _repo_with_overlay(
        tmp_path,
        "doc_types:\n"
        "  adr:\n"
        "    dir_path: decisions\n"
        "    filename: '{slug}.md'\n"
        "    addressing: slug\n"
        "    fields: [rfc]\n",
    )
    monkeypatch.chdir(root)
    _reset_registry_cache()
    from datetime import date

    from reinicorn import frontmatter

    meta = {
        "type": "adr", "title": "T", "slug": "t", "lifecycle": "active",
        "status": "draft", "created": date(2026, 8, 28), "author": "A",
        "origin": "ai-assisted", "human_validated": False, "rfc": "some-rfc",
    }
    assert frontmatter.validate(meta) == []
    meta["bogus"] = "x"
    assert any("bogus" in e for e in frontmatter.validate(meta))
