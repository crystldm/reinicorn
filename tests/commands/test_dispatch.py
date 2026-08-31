"""Tests for CLI dispatch — help, version, unknown command, verb routing."""

from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from reinicorn import __version__
from reinicorn.cli import _build_parser, _dispatch_table, main


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


@pytest.mark.parametrize("noun,argv_tail,expected_branch", [
    ("plan", ["show", "some-branch"], "some-branch"),
    ("retro", ["show"], None),
])
def test_branch_show_dispatches_to_cmd_branch_show(noun, argv_tail, expected_branch):
    with patch(
        "reinicorn.commands.doc_show.cmd_branch_show", return_value=0
    ) as mock_show:
        assert main([noun, *argv_tail]) == 0
    mock_show.assert_called_once_with(noun, expected_branch, full=False)


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
        missing.extend(p for p in pairs if p not in _dispatch_table())
    assert not missing, f"parser verbs without _DISPATCH entries: {missing}"


@pytest.mark.parametrize("noun,argv_tail,expected_args", [
    ("spec", ["create", "My", "Title"], ("spec", "My Title")),
    ("prd", ["create", "My", "Title"], ("prd", "My Title")),
    ("debt", ["create", "My", "Title"], ("debt", "My Title")),
    ("idea", ["create", "some", "idea", "text"], ("idea", "some idea text")),
    ("principle", ["add", "My", "Rule"], ("principle", "My Rule")),
])
def test_create_dispatches_to_cmd_doc_create(noun, argv_tail, expected_args):
    with patch(
        "reinicorn.commands.doc_create.cmd_doc_create", return_value=0
    ) as mock_create:
        assert main([noun, *argv_tail]) == 0
    mock_create.assert_called_once_with(*expected_args)


def test_retro_create_dispatches_without_title():
    with patch(
        "reinicorn.commands.doc_create.cmd_doc_create", return_value=0
    ) as mock_create:
        assert main(["retro", "create"]) == 0
    mock_create.assert_called_once_with("retro")


def test_plan_create_dispatches_to_cmd_plan_create():
    """Plan create must keep routing to the lifecycle-aware entry point,
    not the generic cmd_doc_create."""
    with patch(
        "reinicorn.commands.plan.cmd_plan_create", return_value=0
    ) as mock_create:
        assert main(["plan", "create"]) == 0
    mock_create.assert_called_once_with()


def test_skills_install_dispatches_to_cmd_skills_install():
    with patch(
        "reinicorn.commands.skills_cmds.cmd_skills_install", return_value=0
    ) as mock_install:
        assert main(["skills", "install", "demo"]) == 0
    mock_install.assert_called_once_with("demo")


def test_skills_status_dispatches_to_cmd_skills_status():
    with patch(
        "reinicorn.commands.skills_cmds.cmd_skills_status", return_value=0
    ) as mock_status:
        assert main(["skills", "status"]) == 0
    mock_status.assert_called_once_with()


def test_skills_update_dispatches_to_cmd_skills_update():
    with patch(
        "reinicorn.commands.skills_cmds.cmd_skills_update", return_value=0
    ) as mock_update:
        assert main(["skills", "update"]) == 0
    mock_update.assert_called_once_with(ref=None, force=False)


def test_skills_update_dispatches_ref_and_force_flags():
    sha = "0123456789abcdef0123456789abcdef01234567"
    with patch(
        "reinicorn.commands.skills_cmds.cmd_skills_update", return_value=0
    ) as mock_update:
        assert main(["skills", "update", "--ref", sha, "--force"]) == 0
    mock_update.assert_called_once_with(ref=sha, force=True)


def test_skills_list_dispatches_to_cmd_skills_list():
    with patch(
        "reinicorn.commands.skills_cmds.cmd_skills_list", return_value=0
    ) as mock_list:
        assert main(["skills", "list"]) == 0
    mock_list.assert_called_once_with()
