"""`<type> complete` refusal without a filled required closer, and the
`--abandon` escape (spec: process-as-config §3).

The shipped defaults require nothing, so the requirement comes from an
overlay on the fixture scope — the same way a repo opts in.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from reinicorn import frontmatter as fm
from reinicorn.commands.doc_lifecycle import (
    STATUS_ABANDONED,
    cmd_lifecycle_complete,
)
from tests.conftest import doc_text

REQUIRED_CLOSER = (
    "doc_types:\n"
    "  retro:\n"
    "    closes: {type: plan, required: true}\n"
)

FILLED_RETRO = (
    "# Retro\n\n## What Went Well\n\n- Shipped.\n\n"
    "## What Could Be Improved\n\n- Tests earlier.\n\n"
    "## Lessons Learned\n\n- Write it down.\n\n## Action Items\n\n- None.\n"
)
PLACEHOLDER_RETRO = (
    "# Retro\n\n## What Went Well\n\n- \n\n## What Could Be Improved\n\n- \n\n"
    "## Lessons Learned\n\n- \n\n## Action Items\n\n- \n"
)


@pytest.fixture
def gated_repo(kb_repo: Path, monkeypatch) -> Path:
    """kb_repo whose scope overlay makes the closer required; cwd inside
    it so the cwd-keyed registry reads that overlay."""
    with (kb_repo / ".reinicorn-config").open("a") as f:
        f.write('REINICORN_KB_SCOPE="testproject"\n')
    (kb_repo / "kb" / "testproject" / "doc-types.yaml").write_text(REQUIRED_CLOSER)
    monkeypatch.chdir(kb_repo)
    return kb_repo


def _active_plan(root: Path, name: str, branch: str) -> Path:
    active = root / "kb" / "testproject" / "exec-plans" / "active" / name
    active.mkdir(parents=True)
    (active / "plan.md").write_text(doc_text(
        type="plan", title="Plan", slug=name, status="in-progress",
        branch=branch, spec="N/A", body="\n# Plan\n\n## Goal\n\n- Do it.\n",
    ))
    return active


def _patched(root: Path):
    return (
        patch("reinicorn.commands.doc_lifecycle.repo_root", return_value=root),
        patch("reinicorn.commands.doc_lifecycle.commit_kb"),
    )


def test_complete_refuses_without_required_closer(gated_repo: Path, capsys):
    active = _active_plan(gated_repo, "feature-x", "feature/x")

    root_p, commit_p = _patched(gated_repo)
    with root_p, commit_p as mock_commit:
        rc = cmd_lifecycle_complete("plan", "feature/x")

    assert rc == 1
    assert active.is_dir(), "a refused complete must leave the doc active"
    assert not (
        gated_repo / "kb" / "testproject" / "exec-plans" / "completed" / "feature-x"
    ).exists()
    mock_commit.assert_not_called()
    out = capsys.readouterr().out
    assert "cannot complete" in out
    assert "retro.md is missing" in out
    assert "next: rcorn retro create" in out
    assert "next: rcorn plan complete --abandon" in out


def test_complete_refuses_placeholder_only_closer(gated_repo: Path, capsys):
    active = _active_plan(gated_repo, "feature-y", "feature/y")
    (active / "retro.md").write_text(PLACEHOLDER_RETRO)

    root_p, commit_p = _patched(gated_repo)
    with root_p, commit_p:
        rc = cmd_lifecycle_complete("plan", "feature/y")

    assert rc == 1
    assert active.is_dir()
    assert "only placeholder sections" in capsys.readouterr().out


def test_complete_accepts_filled_required_closer(gated_repo: Path, capsys):
    active = _active_plan(gated_repo, "feature-z", "feature/z")
    (active / "retro.md").write_text(FILLED_RETRO)

    root_p, commit_p = _patched(gated_repo)
    with root_p, commit_p as mock_commit:
        rc = cmd_lifecycle_complete("plan", "feature/z")

    assert rc == 0
    completed = (
        gated_repo / "kb" / "testproject" / "exec-plans" / "completed" / "feature-z"
    )
    assert (completed / "retro.md").is_file()
    assert fm.get((completed / "plan.md").read_text(), "lifecycle") == fm.LIFECYCLE_DONE
    assert "plan: complete feature/z" in mock_commit.call_args[0][1]
    out = capsys.readouterr().out
    assert "No retro captured" not in out


def test_abandon_needs_no_closer_and_stamps_dropped(gated_repo: Path, capsys):
    active = _active_plan(gated_repo, "feature-w", "feature/w")

    root_p, commit_p = _patched(gated_repo)
    with root_p, commit_p as mock_commit:
        rc = cmd_lifecycle_complete("plan", "feature/w", abandon=True)

    assert rc == 0
    assert not active.is_dir()
    completed = (
        gated_repo / "kb" / "testproject" / "exec-plans" / "completed" / "feature-w"
    )
    text = (completed / "plan.md").read_text()
    assert fm.get(text, "status") == STATUS_ABANDONED
    assert fm.get(text, "lifecycle") == fm.LIFECYCLE_DROPPED
    assert "plan: abandon feature/w" in mock_commit.call_args[0][1]
    out = capsys.readouterr().out
    assert "Plan abandoned" in out
    assert "No retro captured" not in out, "an abandoned doc is not nagged for a closer"


def test_optional_closer_still_only_warns(kb_repo: Path, monkeypatch, capsys):
    """The shipped default (`required: false`) keeps today's behavior: the
    move happens and the missing closer is a warning with a next step."""
    monkeypatch.chdir(kb_repo)
    active = _active_plan(kb_repo, "feature-v", "feature/v")

    with patch("reinicorn.kb.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.doc_lifecycle.kb_scope", return_value="testproject"), \
         patch("reinicorn.commands.doc_lifecycle.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.doc_lifecycle.commit_kb"):
        rc = cmd_lifecycle_complete("plan", "feature/v")

    assert rc == 0
    assert not active.is_dir()
    out = capsys.readouterr().out
    assert "No retro captured" in out
    assert "next: rcorn retro create" in out


def test_cli_complete_passes_abandon_flag():
    from reinicorn.cli import _build_parser, _dispatch_table

    args = _build_parser().parse_args(["plan", "complete", "feature/q", "--abandon"])
    assert args.abandon is True
    with patch(
        "reinicorn.commands.doc_lifecycle.cmd_lifecycle_complete", return_value=0,
    ) as mock:
        assert _dispatch_table()[("plan", "complete")](args) == 0
    mock.assert_called_once_with("plan", "feature/q", abandon=True)
