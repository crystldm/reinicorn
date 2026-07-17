"""Test kb scope management commands."""

from __future__ import annotations

from pathlib import Path

from reinicorn.git import run_git
from reinicorn.kb_seed import generate_seed_tree


def _git(*args: str, cwd: Path | None = None) -> None:
    run_git(*args, cwd=cwd)


def test_list_scopes_shows_all_repo_dirs(tmp_path: Path, capsys):
    """cmd_kb_list prints all repo-scoped directories."""
    from reinicorn.commands.kb_manage import cmd_kb_list

    kb = tmp_path / "kb"
    kb.mkdir()
    generate_seed_tree(kb, "repo-alpha")
    generate_seed_tree(kb, "repo-beta")
    (kb / ".gitignore").write_text("generated/\n")

    rc = cmd_kb_list(kb_dir=kb)

    assert rc == 0
    out = capsys.readouterr().out
    assert "repo-alpha" in out
    assert "repo-beta" in out
    assert ".gitignore" not in out


def test_list_scopes_empty_kb(tmp_path: Path, capsys):
    """cmd_kb_list on an empty kb prints a message."""
    from reinicorn.commands.kb_manage import cmd_kb_list

    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / ".gitignore").write_text("generated/\n")

    rc = cmd_kb_list(kb_dir=kb)

    assert rc == 0
    out = capsys.readouterr().out
    assert "No repo scopes" in out


def test_remove_scope_deletes_dir_and_commits(tmp_path: Path, capsys):
    """cmd_kb_remove_scope removes the scope dir and commits."""
    from reinicorn.commands.kb_manage import cmd_kb_remove_scope

    kb = tmp_path / "kb"
    kb.mkdir()
    _git("init", "-q", cwd=kb)
    _git("config", "user.email", "test@test", cwd=kb)
    _git("config", "user.name", "Test", cwd=kb)
    generate_seed_tree(kb, "keep-this")
    generate_seed_tree(kb, "remove-this")
    (kb / ".gitignore").write_text("generated/\n")
    _git("add", "-A", cwd=kb)
    _git("commit", "-q", "-m", "init", cwd=kb)

    rc = cmd_kb_remove_scope("remove-this", kb_dir=kb, push=False, force=True)

    assert rc == 0
    assert not (kb / "remove-this").exists(), "scope dir should be deleted"
    assert (kb / "keep-this").is_dir(), "other scope should remain"
    out = capsys.readouterr().out
    assert "remove-this" in out


def test_remove_scope_rejects_path_traversal(tmp_path: Path, capsys):
    """cmd_kb_remove_scope rejects names with path separators."""
    from reinicorn.commands.kb_manage import cmd_kb_remove_scope

    kb = tmp_path / "kb"
    kb.mkdir()

    rc = cmd_kb_remove_scope("../escape", kb_dir=kb, push=False)

    assert rc == 1
    out = capsys.readouterr().out
    assert "path separators" in out


def test_remove_scope_rejects_empty_name(tmp_path: Path, capsys):
    """An empty scope name must never resolve to the kb root and wipe it."""
    from reinicorn.commands.kb_manage import cmd_kb_remove_scope

    kb = tmp_path / "kb"
    kb.mkdir()
    generate_seed_tree(kb, "keep-this")

    rc = cmd_kb_remove_scope("", kb_dir=kb, push=False, force=True)

    assert rc == 1
    assert kb.is_dir(), "kb root must survive"
    assert (kb / "keep-this").is_dir(), "existing scope must survive"
    assert "Invalid scope name" in capsys.readouterr().out


def test_remove_scope_refuses_noninteractive_without_force(tmp_path: Path, capsys):
    """Without --force in a non-interactive run, removal is refused, not silent."""
    from reinicorn.commands.kb_manage import cmd_kb_remove_scope

    kb = tmp_path / "kb"
    kb.mkdir()
    generate_seed_tree(kb, "remove-this")

    # pytest captures stdout, so sys.stdout.isatty() is False here.
    rc = cmd_kb_remove_scope("remove-this", kb_dir=kb, push=False, force=False)

    assert rc == 1
    assert (kb / "remove-this").is_dir(), "scope must not be deleted"
    assert "--force" in capsys.readouterr().out


def test_remove_scope_nonexistent(tmp_path: Path, capsys):
    """cmd_kb_remove_scope on a missing scope prints an error."""
    from reinicorn.commands.kb_manage import cmd_kb_remove_scope

    kb = tmp_path / "kb"
    kb.mkdir()

    rc = cmd_kb_remove_scope("ghost", kb_dir=kb, push=False)

    assert rc == 1
    out = capsys.readouterr().out
    assert "ghost" in out
