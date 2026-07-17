"""Tests for `rcorn kb status --compact` — session-start ambient context."""

from __future__ import annotations

import pytest

from reinicorn.commands.status import cmd_status


@pytest.fixture(autouse=True)
def _pin_kb_scope(monkeypatch):
    """Pin kb_scope() to "testproject" to match the kb_repo fixture's layout."""
    monkeypatch.setattr("reinicorn.commands.status.kb_scope", lambda _root: "testproject")


def test_compact_is_short_and_undecorated(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    assert cmd_status(compact=True) == 0
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) <= 10
    assert any(ln.startswith("reinicorn: branch main") for ln in lines)
    assert "next: rcorn plan create" in out
    assert "Health" not in out  # no headers, no stale scan


def test_compact_with_plan_suggests_show(kb_repo, monkeypatch, capsys):
    monkeypatch.chdir(kb_repo)
    plan_dir = kb_repo / "kb" / "testproject" / "exec-plans" / "active" / "main"
    plan_dir.mkdir(parents=True, exist_ok=True)
    assert cmd_status(compact=True) == 0
    out = capsys.readouterr().out
    assert "plan present" in out
    assert "next: rcorn plan show" in out
