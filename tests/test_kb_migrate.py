"""Tests for reinicorn.kb_migrate — submodule-to-clone in-place migration."""

from __future__ import annotations

from pathlib import Path

from reinicorn.git import run_git
from reinicorn.kb_migrate import detect_submodule_layout, migrate_submodule_to_clone
from reinicorn.kb_remote import KB_REMOTE_KEY, configured_kb_remote_url


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


def test_migration_records_url_only_when_config_slot_is_empty(
    submodule_repo: Path,
) -> None:
    """An explicitly configured REINICORN_KB_REMOTE (a shared, team-chosen
    URL) must survive migration untouched — it must not be overwritten by
    the resolved URL, which can be a personal override (e.g. an SSH
    rewrite) inherited from the submodule clone being migrated away from."""
    configured = "https://example.invalid/team/kb.git"
    (submodule_repo / ".reinicorn-config").write_text(
        f'{KB_REMOTE_KEY}="{configured}"\n'
    )

    assert migrate_submodule_to_clone(submodule_repo) is True
    assert configured_kb_remote_url(submodule_repo) == configured


def test_migration_backfills_url_when_config_slot_is_empty(
    submodule_repo: Path,
) -> None:
    """Submodule-era repos predate REINICORN_KB_REMOTE — when nothing is
    recorded yet, migration backfills it from the resolved (inherited)
    URL so 'rcorn kb sync' can recover after teardown."""
    assert configured_kb_remote_url(submodule_repo) == ""
    assert migrate_submodule_to_clone(submodule_repo) is True
    assert configured_kb_remote_url(submodule_repo) != ""


def test_migration_keeps_sibling_gitmodules_section(
    submodule_repo: Path, capsys
) -> None:
    """A .gitmodules with an unrelated submodule survives; only kb's section goes."""
    gitmodules = submodule_repo / ".gitmodules"
    with gitmodules.open("a") as f:
        f.write('[submodule "other"]\n\tpath = other\n\turl = /some/other/remote\n')
    run_git("add", ".gitmodules", cwd=submodule_repo)
    run_git("commit", "-q", "-m", "add sibling submodule entry", cwd=submodule_repo)

    assert migrate_submodule_to_clone(submodule_repo) is True

    assert gitmodules.exists()
    text = gitmodules.read_text()
    assert '[submodule "kb"]' not in text
    assert '[submodule "other"]' in text
    assert "path = other" in text

    out = capsys.readouterr().out
    assert ".gitmodules" in out
