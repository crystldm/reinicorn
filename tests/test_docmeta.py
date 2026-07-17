"""Tests for provenance-field helpers."""
from reinicorn.docmeta import get_field, remove_field, set_field

DOC = (
    "# My Spec\n\n"
    "**Date:** 2026-07-06\n"
    "**Author:** Test\n"
    "**Status:** draft\n"
    "**Origin:** ai-assisted\n"
    "\n## Problem\n\nBody **Status:** decoy\n"
)


def test_get_field():
    assert get_field(DOC, "Status") == "draft"
    assert get_field(DOC, "Author") == "Test"
    assert get_field(DOC, "Review-PR") is None


def test_set_existing_field_only_in_header():
    out = set_field(DOC, "Status", "in-review")
    assert "**Status:** in-review" in out
    assert "decoy" in out  # body untouched
    assert out.count("**Status:**") == 2  # header + body decoy


def test_set_new_field_appends_to_header_block():
    out = set_field(DOC, "Review-PR", "https://github.com/x/y/pull/9")
    lines = out.splitlines()
    idx = lines.index("**Review-PR:** https://github.com/x/y/pull/9")
    assert lines[idx - 1] == "**Origin:** ai-assisted"


def test_remove_field():
    out = remove_field(set_field(DOC, "Review-PR", "u"), "Review-PR")
    assert get_field(out, "Review-PR") is None


def test_remove_missing_field_is_noop():
    assert remove_field(DOC, "Review-PR") == DOC


PROSE_DOC = "# My Spec\n\n**Note:** body prose, not a header.\n\nMore body.\n"


def test_prose_decoy_after_title_is_not_a_header():
    assert get_field(PROSE_DOC, "Note") is None
    assert remove_field(PROSE_DOC, "Note") == PROSE_DOC


def test_set_field_on_headerless_doc_inserts_cleanly():
    out = set_field(PROSE_DOC, "Status", "draft")
    lines = out.splitlines()
    idx = lines.index("**Status:** draft")
    assert lines[idx + 1] == ""              # blank separator kept
    assert "**Note:** body prose, not a header." in out
    assert get_field(out, "Note") is None    # prose still not a header
