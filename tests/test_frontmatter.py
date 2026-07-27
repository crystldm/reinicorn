"""Tests for the fenced-YAML frontmatter module.

Field-name and enum literals are asserted raw on purpose (as test_docmeta.py
did for the legacy block): they pin the on-disk format against constant typos.
"""
from datetime import date

import pytest

from reinicorn import frontmatter as fm

DOC = (
    "---\n"
    "type: spec\n"
    "title: My Spec\n"
    "slug: my-spec\n"
    "lifecycle: active\n"
    "status: draft\n"
    "created: 2026-07-06\n"
    "author: Test\n"
    "origin: ai-assisted\n"
    "human_validated: false\n"
    "---\n"
    "\n# My Spec\n\n## Problem\n\nBody **Status:** decoy\n"
)


def _meta(**over):
    base = {
        "type": "spec",
        "title": "My Spec",
        "slug": "my-spec",
        "lifecycle": "active",
        "status": "draft",
        "created": date(2026, 7, 6),
        "author": "Test",
        "origin": "ai-assisted",
        "human_validated": False,
    }
    base.update(over)
    return base


# --- parse / dumps ---------------------------------------------------------

def test_parse_splits_meta_and_body():
    meta, body = fm.parse(DOC)
    assert meta["type"] == "spec"
    assert meta["created"] == date(2026, 7, 6)
    assert meta["human_validated"] is False
    assert body.startswith("\n# My Spec")
    assert "decoy" in body


def test_parse_no_fence_returns_empty_meta_and_whole_text():
    text = "# Plain\n\nNo frontmatter here.\n"
    meta, body = fm.parse(text)
    assert meta == {}
    assert body == text


def test_round_trip_is_byte_exact():
    """Load-bearing: push_candidate asserts the review ref differs from main by
    exactly one added file, and candidate_matches_draft compares exact text."""
    assert fm.dumps(*fm.parse(DOC)) == DOC


def test_body_is_preserved_verbatim_including_blank_lines():
    meta, body = fm.parse(DOC)
    assert fm.dumps(meta, body).endswith(body)


# --- serialization hazards drawn from the real corpus ----------------------

@pytest.mark.parametrize("value", [
    "[TICKET-ID or N/A]",                    # plan template — flow sequence
    "Tech Debt: Output Discipline",          # colon — mapping in mapping
    "implemented — verified end-to-end",     # em dash — allow_unicode
    "Wrap `re.search()` in `try/except`.",   # backticks
    "<https://github.com/x/y/pull/5>",       # leading angle bracket
    "> quoted",                              # folded block scalar
    "yes",                                   # implicit bool
    "no",
    "null",
    "2026-07-19",                            # implicit date
    "*star",                                 # alias
    "&anchor",
    "#hash",
    "  padded  ",
])
def test_hazardous_scalars_round_trip_as_strings(value):
    meta = _meta(status=value)
    text = fm.dumps(meta, "\nbody\n")
    assert fm.parse(text)[0]["status"] == value
    assert fm.dumps(*fm.parse(text)) == text


def test_long_values_are_not_line_wrapped():
    """safe_dump defaults to width=80, which folds long values onto
    continuation lines. tech-debt docs carry full-sentence remediation text."""
    long_value = ("Systematically replace incidental print() calls with the "
                  "appropriate console.* functions across every command module, "
                  "then triage the content-first prints that remain.")
    meta = _meta(type="debt", remediation=long_value)
    text = fm.dumps(meta, "\nbody\n")
    yaml_lines = text.split("---\n")[1].splitlines()
    # One line per key: a folded value would add continuation lines.
    assert len(yaml_lines) == len(meta)
    assert fm.parse(text)[0]["remediation"] == long_value


def test_dates_serialize_bare_not_quoted():
    text = fm.dumps(_meta(), "\nbody\n")
    assert "created: 2026-07-06\n" in text


def test_empty_lists_serialize_inline():
    text = fm.dumps(_meta(tags=[], related=[]), "\nbody\n")
    assert "tags: []\n" in text
    assert "related: []\n" in text


# --- key ordering ----------------------------------------------------------

def _keys_in_order(meta):
    """Top-level keys as serialized. Fence lines and block-sequence items both
    start with '-', so neither is a key."""
    return [ln.split(":")[0] for ln in fm.dumps(meta, "").splitlines()
            if ln and not ln.startswith(("-", " "))]


def test_canonical_key_order():
    meta = _meta(tags=["a"], related=["b"], updated=date(2026, 7, 7))
    keys = _keys_in_order(meta)
    assert keys == [
        "type", "title", "slug", "lifecycle", "status", "created", "updated",
        "author", "origin", "human_validated", "tags", "related",
    ]


def test_per_type_fields_sort_before_tags_and_related():
    keys = _keys_in_order(_meta(type="plan", branch="feat/x",
                                tags=[], related=[]))
    assert keys.index("branch") < keys.index("tags")


def test_unknown_keys_are_kept_not_dropped():
    text = fm.dumps(_meta(zzz_custom="kept"), "")
    assert fm.parse(text)[0]["zzz_custom"] == "kept"


# --- get / set_meta (text-level, used by review.py on git-show output) -----

def test_get_reads_frontmatter_not_body():
    assert fm.get(DOC, "status") == "draft"
    assert fm.get(DOC, "review_pr") is None


def test_set_meta_updates_without_touching_body():
    out = fm.set_meta(DOC, {"status": "in-review"})
    assert fm.get(out, "status") == "in-review"
    assert "Body **Status:** decoy" in out
    assert fm.parse(out)[1] == fm.parse(DOC)[1]


def test_set_meta_none_removes_key():
    staged = fm.set_meta(DOC, {"review_pr": "https://x/y/pull/1"})
    assert fm.get(staged, "review_pr") == "https://x/y/pull/1"
    cleared = fm.set_meta(staged, {"review_pr": None})
    assert fm.get(cleared, "review_pr") is None


def test_set_meta_removing_absent_key_is_noop():
    assert fm.set_meta(DOC, {"review_pr": None}) == DOC


def test_set_meta_is_idempotent():
    once = fm.set_meta(DOC, {"status": "in-review"})
    assert fm.set_meta(once, {"status": "in-review"}) == once


# --- validate --------------------------------------------------------------

def test_valid_meta_has_no_errors():
    assert fm.validate(_meta()) == []


@pytest.mark.parametrize("missing", [
    "type", "title", "slug", "lifecycle", "status", "created", "author",
])
def test_missing_required_core_field_is_an_error(missing):
    meta = _meta()
    del meta[missing]
    assert any(missing in e for e in fm.validate(meta))


def test_type_must_be_a_registry_key():
    assert fm.validate(_meta(type="exec-plan"))  # spec wording is NOT the value
    assert fm.validate(_meta(type="plan", branch="feat/x")) == []


def test_lifecycle_enum_is_enforced():
    assert fm.validate(_meta(lifecycle="in-progress"))
    for ok in ("active", "done", "dropped"):
        assert fm.validate(_meta(lifecycle=ok)) == []


def test_status_stays_free_form():
    assert fm.validate(_meta(status="anything the author likes")) == []


def test_origin_enum_is_enforced():
    assert fm.validate(_meta(origin="robot"))
    for ok in ("human", "ai-assisted"):
        assert fm.validate(_meta(origin=ok)) == []


def test_created_must_be_a_date_not_a_string():
    assert fm.validate(_meta(created="2026-07-06"))


def test_human_validated_must_be_bool():
    assert fm.validate(_meta(human_validated="false"))


def test_tags_and_related_must_be_string_lists():
    assert fm.validate(_meta(tags="a,b"))
    assert fm.validate(_meta(related=[1, 2]))
    assert fm.validate(_meta(tags=["a"], related=["b"])) == []


def test_plan_requires_branch():
    assert any("branch" in e for e in fm.validate(_meta(type="plan")))
    assert fm.validate(_meta(type="plan", branch="feat/x")) == []


def test_retro_requires_branch():
    assert any("branch" in e for e in fm.validate(_meta(type="retro")))


def test_branch_keeps_the_unsanitized_name():
    meta = _meta(type="plan", branch="feature/mvp")
    assert fm.validate(meta) == []
    assert fm.parse(fm.dumps(meta, ""))[0]["branch"] == "feature/mvp"


def test_unknown_key_is_an_error():
    assert any("nonsense" in e for e in fm.validate(_meta(nonsense="x")))


def test_per_type_field_rejected_on_wrong_type():
    assert fm.validate(_meta(type="spec", branch="feat/x"))


def test_review_fields_allowed_on_gated_types_only():
    assert fm.validate(_meta(type="spec", review_pr="https://x/y/pull/1")) == []
    assert fm.validate(_meta(type="idea", review_pr="https://x/y/pull/1"))


def test_missing_frontmatter_reports_one_clear_error():
    assert fm.validate({}) != []


# --- path wrappers ---------------------------------------------------------

def test_read_write_round_trip(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(DOC)
    meta, body = fm.read(p)
    fm.write(p, meta, body)
    assert p.read_text() == DOC


def test_write_creates_parent_dirs(tmp_path):
    p = tmp_path / "nested" / "doc.md"
    fm.write(p, _meta(), "\n# My Spec\n")
    assert fm.read(p)[0]["slug"] == "my-spec"


# --- non-doc exclusions ----------------------------------------------------

@pytest.mark.parametrize("name", [
    "README.md", "index.md", "ATTRIBUTION.md", "quality-scores.md",
    "cleanup-queue.md", "progress.md", "decisions.md",
])
def test_excluded_filenames_are_not_docs(tmp_path, name):
    assert not fm.is_doc(tmp_path / name)


@pytest.mark.parametrize("parts", [
    ("_template", "plan.md"),
    ("tech-debt", "by-category", "security.md"),
    ("references", "gh-pr-review-comments.md"),
])
def test_aggregate_dirs_hold_no_docs(tmp_path, parts):
    assert not fm.is_doc(tmp_path.joinpath(*parts))


def test_debt_doc_beside_the_by_category_rollup_is_a_doc(tmp_path):
    assert fm.is_doc(tmp_path / "tech-debt" / "cli-hints.md")


def test_ordinary_doc_is_a_doc(tmp_path):
    assert fm.is_doc(tmp_path / "specs" / "my-spec.md")


def test_golden_principles_is_a_doc(tmp_path):
    """One aggregate file, but it carries type: principle frontmatter."""
    assert fm.is_doc(tmp_path / "golden-principles.md")


def test_non_markdown_is_not_a_doc(tmp_path):
    assert not fm.is_doc(tmp_path / "notes.txt")
