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


def test_phantom_type_creates_with_no_other_change(kb_repo: Path):
    """Spec's executable design goal, stage-1 slice: a synthetic registry row
    gets working creation from the row alone."""
    from reinicorn.commands.doc_create import cmd_doc_create
    from reinicorn.doc_types import REGISTRY, Addressing, DocType
    phantom = DocType(
        key="phantom", dir_path="phantoms", filename="{slug}.md",
        protected=True,
        help_text="Phantom doc operations",
        template_body="\n## Body\n\n_Filled by {author} on {date}._\n",
        addressing=Addressing.SLUG,
    )
    p1, p2, p3, p4 = _create_env(kb_repo)
    with patch.dict(REGISTRY, {"phantom": phantom}), p1, p2, p3, p4:
        assert cmd_doc_create("phantom", "A Test Doc") == 0
    doc = kb_repo / "kb" / "testproject" / "phantoms" / "a-test-doc.md"
    assert doc.is_file()
    text = doc.read_text()
    assert fm.get(text, "type") == "phantom"
    assert "## Body" in text
    assert "Filled by Test User on" in text


def test_doc_create_refuses_plan_type(kb_repo: Path, capsys):
    """Plan creation has lifecycle logic in cmd_lifecycle_create; the generic
    path must refuse it rather than silently overwrite an active plan."""
    from reinicorn.commands.doc_create import cmd_doc_create
    p1, p2, p3, p4 = _create_env(kb_repo)
    with p1, p2, p3, p4:
        assert cmd_doc_create("plan", "sneaky") == 1
    assert not list(
        (kb_repo / "kb" / "testproject" / "exec-plans" / "active").rglob("plan.md")
    )
    out = capsys.readouterr().out
    assert "error:" in out
    assert "rcorn plan create" in out


# --- {seq} allocation (spec: process-as-config §1) ---


_RFC_OVERLAY = (
    "doc_types:\n"
    "  rfc:\n"
    "    dir_path: rfcs\n"
    "    filename: 'RFC-{seq:04}-{slug}.md'\n"
    "    addressing: slug\n"
)


def _rfc_repo(tmp_path: Path) -> Path:
    from reinicorn.git import run_git

    root = tmp_path / "repo"
    scope_dir = root / "kb" / "myscope"
    scope_dir.mkdir(parents=True)
    (root / "kb" / ".git").mkdir()
    run_git("init", "-q", "-b", "main", str(root))
    (root / ".reinicorn-config").write_text("REINICORN_KB_SCOPE=myscope\n")
    (scope_dir / "doc-types.yaml").write_text(_RFC_OVERLAY)
    return root


def test_seq_allocates_max_plus_one(tmp_path, monkeypatch):
    from reinicorn.commands.doc_create import _next_seq
    from reinicorn.doc_types import registry

    root = _rfc_repo(tmp_path)
    monkeypatch.chdir(root)
    repo_dir = root / "kb" / "myscope"
    rfc = registry(root)["rfc"]
    assert _next_seq(rfc, repo_dir) == 1
    (repo_dir / "rfcs").mkdir()
    (repo_dir / "rfcs" / "RFC-0007-older.md").write_text("x")
    (repo_dir / "rfcs" / "not-an-rfc.md").write_text("x")
    assert _next_seq(rfc, repo_dir) == 8


def test_seq_create_formats_once_and_stamps_id(tmp_path, monkeypatch, capsys):
    from reinicorn.commands.doc_create import cmd_doc_create

    root = _rfc_repo(tmp_path)
    monkeypatch.chdir(root)
    with patch(
        "reinicorn.commands.doc_create.repo_root", return_value=root
    ), patch("reinicorn.commands.doc_create.commit_kb"), patch(
        "reinicorn.commands.doc_create.run_git"
    ) as mock_git:
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        assert cmd_doc_create("rfc", "Use Postgres") == 0

    target = root / "kb" / "myscope" / "rfcs" / "RFC-0001-use-postgres.md"
    assert target.is_file()
    meta = fm.parse(target.read_text())[0]
    assert meta["id"] == "RFC-0001"


def test_seq_show_resolves_id_and_slug(tmp_path, monkeypatch, capsys):
    from reinicorn.commands.doc_create import cmd_doc_create
    from reinicorn.commands.doc_show import cmd_doc_show

    root = _rfc_repo(tmp_path)
    monkeypatch.chdir(root)
    with patch(
        "reinicorn.commands.doc_create.repo_root", return_value=root
    ), patch("reinicorn.commands.doc_create.commit_kb"), patch(
        "reinicorn.commands.doc_create.run_git"
    ) as mock_git:
        mock_git.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Test User\n"
        )
        assert cmd_doc_create("rfc", "Use Postgres") == 0
    capsys.readouterr()

    with patch("reinicorn.commands.doc_show.repo_root", return_value=root):
        assert cmd_doc_show("rfc", "RFC-0001-use-postgres") == 0
        by_slug = capsys.readouterr().out
        assert cmd_doc_show("rfc", "RFC-0001") == 0
        by_id = capsys.readouterr().out
    assert "Use Postgres" in by_slug
    assert "Use Postgres" in by_id


def test_seq_show_reports_ambiguous_id(tmp_path, monkeypatch, capsys):
    from reinicorn.commands.doc_show import cmd_doc_show

    root = _rfc_repo(tmp_path)
    monkeypatch.chdir(root)
    rfcs = root / "kb" / "myscope" / "rfcs"
    rfcs.mkdir()
    for slug in ("one", "two"):
        (rfcs / f"RFC-0001-{slug}.md").write_text(
            f"---\ntype: rfc\nid: RFC-0001\nslug: RFC-0001-{slug}\n---\n\n# {slug}\n"
        )
    with patch("reinicorn.commands.doc_show.repo_root", return_value=root):
        assert cmd_doc_show("rfc", "RFC-0001") == 1
    out = capsys.readouterr().out
    assert "ambiguous" in out
    assert "RFC-0001-one" in out and "RFC-0001-two" in out
