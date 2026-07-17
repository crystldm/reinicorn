"""Tests for reins.submodule — submodule setup with empty-remote handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from reinicorn.git import run_git
from reinicorn.submodule import (
    SubmoduleError,
    cleanup_failed_submodule,
    is_remote_empty,
    seed_remote,
    setup_submodule,
)


def _git(args: list[str], cwd: Path) -> None:
    run_git(*args, cwd=cwd)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q", "-b", "main"], path)
    _git(["config", "user.email", "test@test.com"], path)
    _git(["config", "user.name", "Test User"], path)


@pytest.fixture
def parent_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "parent"
    _init_repo(repo)
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
    _init_repo(staging)
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


def test_setup_submodule_with_seeded_remote(parent_repo: Path, seeded_bare: Path):
    result = setup_submodule(parent_repo, str(seeded_bare))
    assert result is True
    assert (parent_repo / "kb").is_dir()
    assert (parent_repo / ".gitmodules").is_file()


def test_setup_submodule_with_empty_remote_seeds_first(parent_repo: Path, empty_bare: Path):
    result = setup_submodule(parent_repo, str(empty_bare), repo_slug="test-project")
    assert result is True
    assert (parent_repo / "kb").is_dir()


def test_cleanup_failed_submodule(parent_repo: Path):
    """cleanup removes both kb/ dir and .git/modules/kb."""
    kb = parent_repo / "kb"
    kb.mkdir()
    (kb / ".git").write_text("gitdir: ../.git/modules/kb\n")
    modules = parent_repo / ".git" / "modules" / "kb"
    modules.mkdir(parents=True)
    (modules / "HEAD").write_text("ref: refs/heads/main\n")

    cleanup_failed_submodule(parent_repo)
    assert not kb.exists()
    assert not modules.exists()


def test_setup_submodule_error_includes_stderr(parent_repo: Path):
    """setup_submodule should include git stderr in error messages."""
    with pytest.raises(SubmoduleError) as exc_info:
        setup_submodule(parent_repo, "/nonexistent/path/that/does/not/exist.git")
    assert exc_info.value.stderr


def test_setup_submodule_rejects_dangerous_url(parent_repo: Path):
    """A transport-helper URL is refused before it reaches git."""
    with pytest.raises(SubmoduleError, match="Refusing to use kb URL"):
        setup_submodule(parent_repo, "ext::sh -c 'touch pwned'")
    assert not (parent_repo / "pwned").exists()
    assert not (parent_repo / ".gitmodules").exists()


def test_setup_submodule_rejects_option_like_url(parent_repo: Path):
    """An option-like URL cannot inject git flags."""
    with pytest.raises(SubmoduleError, match="Refusing to use kb URL"):
        setup_submodule(parent_repo, "--upload-pack=payload")
