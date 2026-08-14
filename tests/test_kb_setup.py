"""Tests for reinicorn.kb_setup — kb clone setup with empty-remote handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from reinicorn.git import run_git
from reinicorn.kb_setup import (
    KbSetupError,
    cleanup_failed_kb,
    ensure_kb_gitignored,
    is_remote_empty,
    seed_remote,
    setup_kb_clone,
)


def _git(args: list[str], cwd: Path) -> None:
    run_git(*args, cwd=cwd)


def _git_init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q", "-b", "main"], path)
    _git(["config", "user.email", "test@test.com"], path)
    _git(["config", "user.name", "Test User"], path)


@pytest.fixture
def parent_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "parent"
    _git_init(repo)
    (repo / "README.md").write_text("# Test\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    return repo


@pytest.fixture
def empty_bare(tmp_path: Path) -> Path:
    bare = tmp_path / "kb.git"
    bare.mkdir()
    _git(["init", "--bare", "-q"], bare)
    return bare


@pytest.fixture
def seeded_bare(tmp_path: Path) -> Path:
    bare = tmp_path / "kb-seeded.git"
    bare.mkdir()
    _git(["init", "--bare", "-q", "-b", "main"], bare)
    # Seed with a commit
    staging = tmp_path / "staging"
    _git_init(staging)
    (staging / "README.md").write_text("# Kb\n")
    _git(["add", "-A"], staging)
    _git(["commit", "-q", "-m", "init"], staging)
    _git(["-c", "protocol.file.allow=always", "remote", "add", "origin", str(bare)], staging)
    _git(["-c", "protocol.file.allow=always", "push", "-q", "origin", "main"], staging)
    return bare


def test_is_remote_empty_true(empty_bare: Path):
    assert is_remote_empty(str(empty_bare)) is True


def test_is_remote_empty_false(seeded_bare: Path):
    assert is_remote_empty(str(seeded_bare)) is False


def test_seed_remote_populates_empty(empty_bare: Path, tmp_path: Path):
    seed_remote(str(empty_bare), repo_slug="test-project")
    # Should now have refs
    assert is_remote_empty(str(empty_bare)) is False


def test_setup_kb_clone_with_seeded_remote(parent_repo: Path, seeded_bare: Path):
    result = setup_kb_clone(parent_repo, str(seeded_bare))
    assert result is True
    assert (parent_repo / "kb").is_dir()
    assert (parent_repo / "kb" / ".git").is_dir()


def test_setup_kb_clone_with_empty_remote_seeds_first(parent_repo: Path, empty_bare: Path):
    result = setup_kb_clone(parent_repo, str(empty_bare), repo_slug="test-project")
    assert result is True
    assert (parent_repo / "kb").is_dir()


def test_cleanup_failed_kb(parent_repo: Path):
    """cleanup removes both kb/ dir and .git/modules/kb."""
    kb = parent_repo / "kb"
    kb.mkdir()
    (kb / ".git").write_text("gitdir: ../.git/modules/kb\n")
    modules = parent_repo / ".git" / "modules" / "kb"
    modules.mkdir(parents=True)
    (modules / "HEAD").write_text("ref: refs/heads/main\n")

    cleanup_failed_kb(parent_repo)
    assert not kb.exists()
    assert not modules.exists()


def test_setup_kb_clone_error_includes_stderr(parent_repo: Path):
    """setup_kb_clone surfaces git's own output in the error message.

    Asserted on the message rather than an attribute: the message is what the
    user actually reads, and git.explain_failure is now the only thing that
    builds it.
    """
    with pytest.raises(KbSetupError) as exc_info:
        setup_kb_clone(parent_repo, "/nonexistent/path/that/does/not/exist.git")
    message = str(exc_info.value)
    assert "Could not clone the kb" in message
    assert "git: " in message
    assert "/nonexistent/path/that/does/not/exist.git" in message


def test_setup_kb_clone_rejects_dangerous_url(parent_repo: Path):
    """A transport-helper URL is refused before it reaches git."""
    with pytest.raises(KbSetupError, match="Refusing to use kb URL"):
        setup_kb_clone(parent_repo, "ext::sh -c 'touch pwned'")
    assert not (parent_repo / "pwned").exists()
    assert not (parent_repo / "kb").exists()


def test_setup_kb_clone_rejects_option_like_url(parent_repo: Path):
    """An option-like URL cannot inject git flags."""
    with pytest.raises(KbSetupError, match="Refusing to use kb URL"):
        setup_kb_clone(parent_repo, "--upload-pack=payload")


def test_setup_kb_clone_creates_plain_clone(tmp_path):
    bare = tmp_path / "remote.git"
    run_git("init", "-q", "--bare", "-b", "main", str(bare))
    target = tmp_path / "proj"
    target.mkdir()
    _git_init(target)

    assert setup_kb_clone(target, str(bare.resolve()), repo_slug="proj") is True
    kb = target / "kb"
    assert (kb / ".git").is_dir()                      # a clone, not a submodule
    assert not (target / ".gitmodules").exists()
    assert "kb/" in (target / ".gitignore").read_text()
    r = run_git("symbolic-ref", "--short", "HEAD", cwd=kb)
    assert r.stdout.strip() == "main"


def test_ensure_kb_gitignored_idempotent(tmp_path):
    root = tmp_path
    (root / ".gitignore").write_text("*.pyc\n")
    assert ensure_kb_gitignored(root) is True
    assert ensure_kb_gitignored(root) is False
    assert (root / ".gitignore").read_text() == "*.pyc\nkb/\n"
