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
