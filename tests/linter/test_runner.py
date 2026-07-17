"""Tests for the lint runner."""

from __future__ import annotations

from pathlib import Path

from reinicorn.linter.runner import run_lints


def test_runner_no_config(tmp_path: Path, capsys):
    result = run_lints(tmp_path)
    assert result == 1
    assert "FATAL" in capsys.readouterr().out


def test_runner_invalid_json(tmp_path: Path, capsys):
    linters = tmp_path / "linters"
    linters.mkdir()
    (linters / ".lint-config.json").write_text("not json")
    result = run_lints(tmp_path)
    assert result == 1


def test_runner_all_pass(kb_repo: Path, capsys):
    # Create an AGENTS.md with no broken links
    (kb_repo / "AGENTS.md").write_text("# Agents\n\nNo links here.\n")

    run_lints(kb_repo)
    out = capsys.readouterr().out
    assert "Lint Summary" in out
    # cross-links should pass (no broken links), plan-structure should pass (no active plans)
    assert "PASS" in out
