"""`rcorn _process-gate <branch>` — the pre-merge check, scoped to one
branch's docs (spec: process-as-config §3)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from tests.conftest import doc_text

from reinicorn.commands.internal.process_gate import branch_docs, cmd_process_gate
from reinicorn.git import run_git
from reinicorn.linter.rules.base import diagnostic_path

GOOD_BODY = (
    "\n# Plan\n\n## Goal\n\n- Do it.\n\n## Acceptance Criteria\n\n- Done.\n\n"
    "## Tasks\n\n- [ ] one\n"
)


@pytest.fixture
def gate_repo(kb_repo: Path, monkeypatch) -> Path:
    with (kb_repo / ".reinicorn-config").open("a") as f:
        f.write('REINICORN_KB_SCOPE="testproject"\n')
    monkeypatch.chdir(kb_repo)
    return kb_repo


def _plan(root: Path, name: str, branch: str, body: str = GOOD_BODY) -> Path:
    active = root / "kb" / "testproject" / "exec-plans" / "active" / name
    active.mkdir(parents=True, exist_ok=True)
    (active / "plan.md").write_text(doc_text(
        type="plan", title="Plan", slug=name, status="in-progress",
        branch=branch, spec="N/A", body=body,
    ))
    run_git("add", "-A", cwd=root / "kb")
    return active


def _run(root: Path, branch: str) -> int:
    with patch("reinicorn.commands.internal.process_gate.repo_root", return_value=root):
        return cmd_process_gate([branch])


def test_no_governed_docs_passes(gate_repo: Path, capsys):
    assert _run(gate_repo, "feature/none") == 0
    assert "No governed docs" in capsys.readouterr().out


def test_gate_judges_only_the_named_branch(gate_repo: Path, capsys):
    _plan(gate_repo, "feature-good", "feature/good")
    _plan(gate_repo, "feature-bad", "feature/bad", body="\n# Plan\n\nno sections\n")

    assert _run(gate_repo, "feature/good") == 0
    out = capsys.readouterr().out
    assert "[PASS] kb/required-sections" in out
    assert "feature-bad" not in out, "another branch's findings must not red this one"

    assert _run(gate_repo, "feature/bad") == 1
    out = capsys.readouterr().out
    assert "[FAIL] kb/required-sections" in out
    assert "exec-plans/active/feature-bad/plan.md" in out
    assert "process gate failed" in out


def test_missing_doc_in_branch_dir_is_not_filtered_away(gate_repo: Path, capsys):
    active = gate_repo / "kb" / "testproject" / "exec-plans" / "active" / "feature-empty"
    active.mkdir(parents=True)
    (active / "notes.md").write_text("# notes\n")

    assert _run(gate_repo, "feature/empty") == 1
    assert "Missing plan.md" in capsys.readouterr().out


def test_required_closer_blocks_the_gate(gate_repo: Path, capsys):
    (gate_repo / "kb" / "testproject" / "doc-types.yaml").write_text(
        "doc_types:\n  retro:\n    closes: {type: plan, required: true}\n"
    )
    _plan(gate_repo, "feature-open", "feature/open")

    assert _run(gate_repo, "feature/open") == 1
    out = capsys.readouterr().out
    assert "[FAIL] kb/closer-filled" in out
    assert "rcorn retro create" in out


def test_completed_stage_docs_belong_to_the_branch(gate_repo: Path):
    completed = gate_repo / "kb" / "testproject" / "exec-plans" / "completed" / "feature-old"
    completed.mkdir(parents=True)
    (completed / "plan.md").write_text("# old\n")
    (completed / "retro.md").write_text("# retro\n")

    docs = branch_docs(gate_repo, gate_repo / "kb", "feature/old")
    assert docs == {
        "kb/testproject/exec-plans/completed/feature-old/plan.md",
        "kb/testproject/exec-plans/completed/feature-old/retro.md",
    }


def test_gate_needs_a_branch(capsys):
    with patch("reinicorn.commands.internal.process_gate.current_branch", return_value=""):
        assert cmd_process_gate([]) == 2
    assert "no branch to gate" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("diagnostic", "path"),
    [
        ("kb/x/plan.md:12 — Missing '## Goal' section.", "kb/x/plan.md"),
        ("kb/x/a:b.md:1 — odd name", "kb/x/a:b.md"),
    ],
)
def test_diagnostic_path(diagnostic: str, path: str):
    assert diagnostic_path(diagnostic) == path
