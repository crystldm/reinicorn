"""Tests for reinicorn <type> create commands."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from reinicorn import frontmatter as fm
from reinicorn.commands.doc_create import cmd_doc_check_path

# --- cmd_doc_check_path tests ---


def test_check_path_blocks_new_spec_doc(tmp_path: Path):
    new_file = tmp_path / "kb" / "myrepo" / "specs" / "new-feature.md"
    result = cmd_doc_check_path(str(new_file))
    assert result == 2


def test_check_path_allows_existing_file(tmp_path: Path):
    existing = tmp_path / "kb" / "myrepo" / "specs" / "existing.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("# Existing\n")
    result = cmd_doc_check_path(str(existing))
    assert result == 0


def test_check_path_allows_non_kb_file(tmp_path: Path):
    result = cmd_doc_check_path(str(tmp_path / "src" / "something.md"))
    assert result == 0


def test_check_path_allows_non_md_file(tmp_path: Path):
    result = cmd_doc_check_path(str(tmp_path / "kb" / "myrepo" / "specs" / "foo.py"))
    assert result == 0


def test_check_path_blocks_new_idea(tmp_path: Path):
    new_file = tmp_path / "kb" / "myrepo" / "ideas" / "user" / "new-idea.md"
    result = cmd_doc_check_path(str(new_file))
    assert result == 2


def test_check_path_blocks_new_plan(tmp_path: Path):
    new_file = (
        tmp_path / "kb" / "myrepo" / "exec-plans" / "active" / "feature-x" / "plan.md"
    )
    result = cmd_doc_check_path(str(new_file))
    assert result == 2


def test_check_path_allows_progress_md(tmp_path: Path):
    new_file = (
        tmp_path / "kb" / "myrepo" / "exec-plans" / "active" / "feature-x" / "progress.md"
    )
    result = cmd_doc_check_path(str(new_file))
    assert result == 0


# --- per-type entry point tests ---


def test_cmd_spec_create_creates_doc(kb_repo: Path):
    """Spec is a gated doc type, so create scaffolds into the drafts/ annex."""
    from reinicorn.commands.doc_create import cmd_doc_create
    with patch("reinicorn.commands.doc_create.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.doc_create.run_git") as mock_git, \
         patch("reinicorn.commands.doc_create.commit_kb"), \
         patch("reinicorn.commands.doc_create.kb_scope", return_value="testproject"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_doc_create("spec", "My Feature")
    assert result == 0
    doc = kb_repo / "kb" / "testproject" / "specs" / "drafts" / "my-feature.md"
    assert doc.is_file()


def test_spec_create_writes_to_drafts(kb_repo: Path, capsys):
    """Gated doc types (spec) land in the drafts/ annex with Status: draft."""
    from reinicorn.commands.doc_create import cmd_doc_create
    with patch("reinicorn.commands.doc_create.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.doc_create.run_git") as mock_git, \
         patch("reinicorn.commands.doc_create.commit_kb"), \
         patch("reinicorn.commands.doc_create.kb_scope", return_value="testproject"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_doc_create("spec", "My Gated Spec")
    assert result == 0
    doc = kb_repo / "kb" / "testproject" / "specs" / "drafts" / "my-gated-spec.md"
    assert doc.is_file()
    assert fm.get(doc.read_text(), "status") == "draft"
    out = capsys.readouterr().out
    assert "next: rcorn review start my-gated-spec" in out


def test_prd_create_stays_flat(kb_repo: Path, capsys):
    """Non-gated doc types (prd) are unaffected and still land flat."""
    from reinicorn.commands.doc_create import cmd_doc_create
    with patch("reinicorn.commands.doc_create.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.doc_create.run_git") as mock_git, \
         patch("reinicorn.commands.doc_create.commit_kb"), \
         patch("reinicorn.commands.doc_create.kb_scope", return_value="testproject"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_doc_create("prd", "My PRD")
    assert result == 0
    doc = kb_repo / "kb" / "testproject" / "prds" / "my-prd.md"
    assert doc.is_file()
    assert not (kb_repo / "kb" / "testproject" / "prds" / "drafts").exists()
    assert "review start" not in capsys.readouterr().out


def test_check_path_blocks_drafts(tmp_path: Path):
    """New files under specs/drafts/ are still protected (not a bypass)."""
    new_file = tmp_path / "kb" / "myrepo" / "specs" / "drafts" / "new-spec.md"
    result = cmd_doc_check_path(str(new_file))
    assert result == 2


def _create_env(kb_repo: Path):
    """Patches shared by the create-collision tests."""
    return (
        patch("reinicorn.commands.doc_create.repo_root", return_value=kb_repo),
        patch("reinicorn.commands.doc_create.run_git", return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )),
        patch("reinicorn.commands.doc_create.commit_kb"),
        patch("reinicorn.commands.doc_create.kb_scope", return_value="testproject"),
    )


def test_spec_create_refuses_when_slug_already_landed(kb_repo: Path, capsys):
    """Gated create must not draft a slug whose canonical path is occupied —
    the review lane would otherwise mistake the old doc for a merged review."""
    final = kb_repo / "kb" / "testproject" / "specs" / "my-feature.md"
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_text("# My Feature\n\n**Status:** approved\n")
    from reinicorn.commands.doc_create import cmd_doc_create
    p1, p2, p3, p4 = _create_env(kb_repo)
    with p1, p2, p3, p4:
        assert cmd_doc_create("spec", "My Feature") == 1
    assert not (
        kb_repo / "kb" / "testproject" / "specs" / "drafts" / "my-feature.md"
    ).exists()
    out = capsys.readouterr().out
    assert "error:" in out
    assert "my-feature" in out


def test_spec_create_refuses_to_clobber_existing_draft(kb_repo: Path, capsys):
    draft = kb_repo / "kb" / "testproject" / "specs" / "drafts" / "my-feature.md"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("# My Feature\n\n**Status:** draft\n\nprecious edits\n")
    from reinicorn.commands.doc_create import cmd_doc_create
    p1, p2, p3, p4 = _create_env(kb_repo)
    with p1, p2, p3, p4:
        assert cmd_doc_create("spec", "My Feature") == 1
    assert "precious edits" in draft.read_text()
    assert "error:" in capsys.readouterr().out


def test_prd_create_refuses_to_clobber_existing_doc(kb_repo: Path, capsys):
    """Non-gated slug-addressed creates get the same no-clobber guard."""
    doc = kb_repo / "kb" / "testproject" / "prds" / "my-prd.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# My PRD\n\nprecious edits\n")
    from reinicorn.commands.doc_create import cmd_doc_create
    p1, p2, p3, p4 = _create_env(kb_repo)
    with p1, p2, p3, p4:
        assert cmd_doc_create("prd", "My PRD") == 1
    assert "precious edits" in doc.read_text()
    assert "error:" in capsys.readouterr().out


def test_cmd_prd_create_creates_doc(kb_repo: Path):
    from reinicorn.commands.doc_create import cmd_doc_create
    with patch("reinicorn.commands.doc_create.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.doc_create.run_git") as mock_git, \
         patch("reinicorn.commands.doc_create.commit_kb"), \
         patch("reinicorn.commands.doc_create.kb_scope", return_value="testproject"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_doc_create("prd", "My Spec")
    assert result == 0
    doc = kb_repo / "kb" / "testproject" / "prds" / "my-spec.md"
    assert doc.is_file()


def test_cmd_debt_create_creates_doc(kb_repo: Path):
    from reinicorn.commands.doc_create import cmd_doc_create
    with patch("reinicorn.commands.doc_create.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.doc_create.run_git") as mock_git, \
         patch("reinicorn.commands.doc_create.commit_kb"), \
         patch("reinicorn.commands.doc_create.kb_scope", return_value="testproject"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_doc_create("debt", "Old coupling")
    assert result == 0
    doc = kb_repo / "kb" / "testproject" / "tech-debt" / "old-coupling.md"
    assert doc.is_file()


def test_cmd_retro_create_uses_branch(kb_repo: Path):
    from reinicorn.commands.doc_create import cmd_doc_create
    with patch("reinicorn.commands.doc_create.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.doc_create.run_git") as mock_git, \
         patch("reinicorn.commands.doc_create.commit_kb"), \
         patch("reinicorn.commands.doc_create.current_branch", return_value="feature/x"), \
         patch("reinicorn.commands.doc_create.kb_scope", return_value="testproject"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_doc_create("retro", "")
    assert result == 0
    doc = (kb_repo / "kb" / "testproject" / "exec-plans"
           / "completed" / "feature-x" / "retro.md")
    assert doc.is_file()


def test_cmd_retro_create_commit_message_uses_branch(kb_repo: Path):
    """Retro commit message must include the branch slug, not an empty title."""
    from reinicorn.commands.doc_create import cmd_doc_create
    with patch("reinicorn.commands.doc_create.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.doc_create.run_git") as mock_git, \
         patch("reinicorn.commands.doc_create.commit_kb") as mock_commit, \
         patch("reinicorn.commands.doc_create.current_branch", return_value="feature/x"), \
         patch("reinicorn.commands.doc_create.kb_scope", return_value="testproject"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_doc_create("retro", "")
    assert result == 0
    msg = mock_commit.call_args[0][1]
    assert msg == "doc(retro): feature-x", f"unexpected commit message: {msg!r}"
    # Commit is scoped to the created file (issue #35)
    expected = (kb_repo / "kb" / "testproject" / "exec-plans"
                / "completed" / "feature-x" / "retro.md")
    assert mock_commit.call_args.kwargs["paths"] == [expected]
    assert expected.is_file()


def test_cmd_retro_create_heading_contains_branch(kb_repo: Path):
    """Retro file heading must include the branch name (derived inside _create_retro)."""
    from reinicorn.commands.doc_create import cmd_doc_create
    with patch("reinicorn.commands.doc_create.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.doc_create.run_git") as mock_git, \
         patch("reinicorn.commands.doc_create.commit_kb"), \
         patch("reinicorn.commands.doc_create.current_branch", return_value="feature/x"), \
         patch("reinicorn.commands.doc_create.kb_scope", return_value="testproject"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_doc_create("retro", "")
    assert result == 0
    doc = (kb_repo / "kb" / "testproject" / "exec-plans"
           / "completed" / "feature-x" / "retro.md")
    assert doc.is_file()
    content = doc.read_text()
    assert "# Retro: feature/x" in content


def test_doc_create_unknown_type_returns_error():
    """cmd_doc_create must guard against unknown doc types."""
    from reinicorn.commands.doc_create import cmd_doc_create
    assert cmd_doc_create("nonexistent", "some title") == 1


def test_doc_create_empty_title_rejected_for_title_types():
    from reinicorn.commands.doc_create import cmd_doc_create
    assert cmd_doc_create("spec", "") == 1
    assert cmd_doc_create("spec", "   ") == 1


def test_debt_create_carries_static_extra_meta(kb_repo: Path):
    """Debt's severity/category/remediation now come from REGISTRY.extra_meta."""
    from reinicorn.commands.doc_create import cmd_doc_create
    p1, p2, p3, p4 = _create_env(kb_repo)
    with p1, p2, p3, p4:
        assert cmd_doc_create("debt", "Old coupling") == 0
    doc = kb_repo / "kb" / "testproject" / "tech-debt" / "old-coupling.md"
    text = doc.read_text()
    assert fm.get(text, "severity") == "medium"
    assert fm.get(text, "category") == "_domain_"
    assert fm.get(text, "remediation") == "planned"


def test_principle_add_appends_numbered_item(kb_repo: Path):
    """Second add appends item 2 to the singleton file, no new file."""
    from reinicorn.commands.doc_create import cmd_doc_create
    p1, p2, p3, p4 = _create_env(kb_repo)
    with p1, p2, p3, p4:
        assert cmd_doc_create("principle", "First rule") == 0
        assert cmd_doc_create("principle", "Second rule") == 0
    doc = kb_repo / "kb" / "testproject" / "golden-principles.md"
    content = doc.read_text()
    assert "1. **First rule**" in content
    assert "2. **Second rule**" in content
    assert fm.get(content, "status") == "active"


def test_create_suggests_publish(kb_repo, monkeypatch, capsys):
    from reinicorn.commands.doc_create import cmd_doc_create
    monkeypatch.chdir(kb_repo)
    assert cmd_doc_create("spec", "My Spec") == 0
    out = capsys.readouterr().out
    assert "next: rcorn kb publish" in out


def test_cmd_principle_add(kb_repo: Path):
    from reinicorn.commands.doc_create import cmd_doc_create
    with patch("reinicorn.commands.doc_create.repo_root", return_value=kb_repo), \
         patch("reinicorn.commands.doc_create.run_git") as mock_git, \
         patch("reinicorn.commands.doc_create.commit_kb"), \
         patch("reinicorn.commands.doc_create.kb_scope", return_value="testproject"):
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        result = cmd_doc_create("principle", "Always test")
    assert result == 0
    doc = kb_repo / "kb" / "testproject" / "golden-principles.md"
    assert doc.is_file()
    assert "Always test" in doc.read_text()
