"""Tests for reinicorn.kb_migrate — submodule-to-clone in-place migration."""

from __future__ import annotations

from pathlib import Path

from reinicorn.git import run_git
from reinicorn.kb_migrate import detect_submodule_layout, migrate_submodule_to_clone


def test_detect_by_gitmodules(submodule_repo: Path) -> None:
    assert detect_submodule_layout(submodule_repo) is True


def test_detect_orphan_gitlink(submodule_repo: Path) -> None:
    """A tracked 160000 kb entry with no .gitmodules still migrates (spec §10)."""
    (submodule_repo / ".gitmodules").unlink()
    run_git("add", ".gitmodules", cwd=submodule_repo)
    run_git("commit", "-q", "-m", "orphan the gitlink", cwd=submodule_repo)
    assert detect_submodule_layout(submodule_repo) is True


def test_detect_clone_layout_is_false(kb_clone_repo: Path) -> None:
    assert detect_submodule_layout(kb_clone_repo) is False


def test_migration_refuses_uncommitted_kb_work(submodule_repo: Path) -> None:
    (submodule_repo / "kb" / "draft.md").write_text("unpublished draft\n")
    assert migrate_submodule_to_clone(submodule_repo) is False
    assert (submodule_repo / "kb" / "draft.md").read_text() == "unpublished draft\n"
    # Nothing destructive ran: still a submodule
    assert detect_submodule_layout(submodule_repo) is True


def test_migration_refuses_unpushed_kb_commits(submodule_repo: Path) -> None:
    kb = submodule_repo / "kb"
    (kb / "draft.md").write_text("committed, unpushed\n")
    run_git("add", "-A", cwd=kb)
    run_git("commit", "-q", "-m", "local only", cwd=kb)
    assert migrate_submodule_to_clone(submodule_repo) is False
    assert detect_submodule_layout(submodule_repo) is True


def test_migration_converts_clean_repo(submodule_repo: Path) -> None:
    assert migrate_submodule_to_clone(submodule_repo) is True
    kb = submodule_repo / "kb"
    assert (kb / ".git").is_dir()  # plain clone now
    assert not (submodule_repo / ".gitmodules").exists()
    assert "kb/" in (submodule_repo / ".gitignore").read_text()
    # gitlink removal is staged for the user to commit
    r = run_git("diff", "--cached", "--name-only", cwd=submodule_repo)
    assert "kb" in r.stdout.splitlines()
    # submodule config gone
    r = run_git(
        "config", "--get", "submodule.kb.url", check=False, cwd=submodule_repo
    )
    assert r.returncode != 0


def test_migration_handles_orphan_gitlink(submodule_repo: Path) -> None:
    (submodule_repo / ".gitmodules").unlink()
    run_git("add", ".gitmodules", cwd=submodule_repo)
    run_git("commit", "-q", "-m", "orphan", cwd=submodule_repo)
    assert migrate_submodule_to_clone(submodule_repo) is True
    assert (submodule_repo / "kb" / ".git").is_dir()
