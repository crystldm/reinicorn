"""Registry-driven CLI generation: a registry row is the only source of a
doc type's parser surface (spec: registry-driven-doc-types, stage 2)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from reinicorn.cli import _build_parser
from reinicorn.doc_types import REGISTRY, Addressing, DocType

PHANTOM = DocType(
    key="phantom", dir_path="phantoms", filename="{slug}.md",
    protected=True, create_hint='rcorn phantom create "<title>"',
    help_text="Phantom doc operations",
    template_body="\n## Body\n\n_Text._\n",
    addressing=Addressing.SLUG,
)


def test_phantom_row_gets_parser_surface():
    with patch.dict(REGISTRY, {"phantom": PHANTOM}):
        parser = _build_parser()
        args = parser.parse_args(["phantom", "create", "My", "Doc"])
        assert args.title == ["My", "Doc"]
        args = parser.parse_args(["phantom", "show", "my-doc", "--include-drafts"])
        assert args.slug == "my-doc" and args.include_drafts is True
        args = parser.parse_args(["phantom", "list"])
        assert args.include_drafts is False


def test_phantom_row_absent_without_patch():
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["phantom", "list"])


def test_phantom_row_gets_dispatch_rows():
    from reinicorn.cli import _doc_dispatch_rows
    with patch.dict(REGISTRY, {"phantom": PHANTOM}):
        rows = _doc_dispatch_rows()
    for verb in ("create", "show", "list"):
        assert ("phantom", verb) in rows


def test_phantom_create_end_to_end(kb_repo):
    """Parser + generated row + generic creator: the registry row alone
    yields a working `phantom create` (spec's executable design goal)."""
    from reinicorn.cli import _doc_dispatch_rows
    from tests.commands.test_doc_create import _create_env
    p1, p2, p3, p4 = _create_env(kb_repo)
    with patch.dict(REGISTRY, {"phantom": PHANTOM}), p1, p2, p3, p4:
        args = _build_parser().parse_args(["phantom", "create", "A", "Test", "Doc"])
        assert _doc_dispatch_rows()[("phantom", "create")](args) == 0
    assert (kb_repo / "kb" / "testproject" / "phantoms" / "a-test-doc.md").is_file()
