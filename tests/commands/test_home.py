"""Tests for the bare `reinicorn` content-first home view (axi principle 8)."""

from __future__ import annotations

import pytest

from reinicorn.commands.home import cmd_home


@pytest.fixture(autouse=True)
def _pin_kb_scope(monkeypatch):
    """Pin kb_scope() to "testproject" to match the kb_repo fixture's layout."""
    monkeypatch.setattr("reinicorn.commands.home.kb_scope", lambda _root: "testproject")


def test_home_shows_live_state_not_usage(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    assert cmd_home() == 0
    out = capsys.readouterr().out
    assert "bin: " in out
    assert "branch: main" in out
    assert "plan: none for this branch" in out
    assert "overlap: none" in out
    assert "next: rcorn plan create" in out
    assert "usage:" not in out


def test_home_outside_git_repo_is_definitive(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cmd_home() == 0
    out = capsys.readouterr().out
    assert "repo: not inside a git repository" in out
    assert "next: rcorn help" in out


def test_bare_reins_invokes_home(kb_repo, monkeypatch, capsys):
    from reinicorn.cli import main

    monkeypatch.chdir(kb_repo)
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "branch: main" in out
    assert "usage:" not in out


def test_home_uninitialized_kb_submodule(kb_repo, monkeypatch, capsys):
    """Fresh clone: .gitmodules declares kb but the submodule dir is absent."""
    import shutil

    shutil.rmtree(kb_repo / "kb")
    monkeypatch.chdir(kb_repo)
    assert cmd_home() == 0
    out = capsys.readouterr().out
    assert "kb: submodule not initialized" in out
    assert "next: git submodule update --init kb" in out


def test_home_no_kb_setup(kb_repo, monkeypatch, capsys):
    """Git repo with no .gitmodules at all — kb never set up."""
    (kb_repo / ".gitmodules").unlink()
    monkeypatch.chdir(kb_repo)
    assert cmd_home() == 0
    out = capsys.readouterr().out
    assert "kb: not set up in this repo" in out
    assert "next: rcorn init" in out


def test_home_plan_present_for_branch(kb_repo, monkeypatch, capsys):
    (kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "main").mkdir()
    monkeypatch.chdir(kb_repo)
    assert cmd_home() == 0
    out = capsys.readouterr().out
    assert "plan: main (this branch)" in out
    assert "next: rcorn plan show" in out
