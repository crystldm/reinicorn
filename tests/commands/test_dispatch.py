"""Tests for CLI dispatch — help, version, unknown command, verb routing."""

from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from reinicorn import __version__
from reinicorn.cli import _DISPATCH, _build_parser, main


def test_help_returns_zero(capsys):
    assert main(["help"]) == 0
    out = capsys.readouterr().out
    assert "reinicorn" in out
    assert "sync" in out
    assert "publish" in out


def test_help_flag(capsys):
    assert main(["--help"]) == 0


def test_help_short_flag(capsys):
    assert main(["-h"]) == 0


def test_version_flag(capsys):
    assert main(["--version"]) == 0
    out = capsys.readouterr().out
    assert __version__ in out


def test_unknown_command_returns_nonzero(capsys):
    assert main(["nonexistent"]) != 0


@pytest.mark.parametrize("noun", ["spec", "prd", "debt", "idea"])
def test_list_dispatches_to_cmd_doc_list(noun):
    with patch("reinicorn.commands.doc_show.cmd_doc_list", return_value=0) as mock_list:
        assert main([noun, "list"]) == 0
    mock_list.assert_called_once_with(noun, include_drafts=False)


@pytest.mark.parametrize("noun", ["spec", "prd", "debt", "idea"])
def test_show_dispatches_to_cmd_doc_show(noun):
    with patch("reinicorn.commands.doc_show.cmd_doc_show", return_value=0) as mock_show:
        assert main([noun, "show", "my-slug", "--full"]) == 0
    mock_show.assert_called_once_with(noun, "my-slug", full=True, include_drafts=False)


@pytest.mark.parametrize("noun", ["spec", "prd", "debt", "idea"])
def test_show_dispatches_include_drafts_flag(noun):
    with patch("reinicorn.commands.doc_show.cmd_doc_show", return_value=0) as mock_show:
        assert main([noun, "show", "my-slug", "--include-drafts"]) == 0
    mock_show.assert_called_once_with(noun, "my-slug", full=False, include_drafts=True)


@pytest.mark.parametrize("noun", ["spec", "prd", "debt", "idea"])
def test_list_dispatches_include_drafts_flag(noun):
    with patch("reinicorn.commands.doc_show.cmd_doc_list", return_value=0) as mock_list:
        assert main([noun, "list", "--include-drafts"]) == 0
    mock_list.assert_called_once_with(noun, include_drafts=True)


def test_plan_show_dispatches_to_cmd_plan_show():
    with patch("reinicorn.commands.doc_show.cmd_plan_show", return_value=0) as mock_show:
        assert main(["plan", "show", "some-branch"]) == 0
    mock_show.assert_called_once_with("some-branch", full=False)


def test_retro_show_dispatches_to_cmd_retro_show():
    with patch("reinicorn.commands.doc_show.cmd_retro_show", return_value=0) as mock_show:
        assert main(["retro", "show"]) == 0
    mock_show.assert_called_once_with(None, full=False)


def _subparser_choices(parser: argparse.ArgumentParser):
    """Return the {name: subparser} dict of a parser, or None if it has no subparsers."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return None


def test_every_parser_verb_has_a_dispatch_entry():
    """Adding a verb to the parser without a _DISPATCH entry must fail this test."""
    nouns = _subparser_choices(_build_parser())
    assert nouns, "top-level subparsers not found"
    missing = []
    for noun, group in nouns.items():
        if noun == "help":
            continue  # handled in main() before dispatch
        verbs = _subparser_choices(group)
        # Nouns with no verbs (init, update, feedback) dispatch as (noun, None).
        pairs = [(noun, None)] if verbs is None else [(noun, v) for v in verbs]
        missing.extend(p for p in pairs if p not in _DISPATCH)
    assert not missing, f"parser verbs without _DISPATCH entries: {missing}"
