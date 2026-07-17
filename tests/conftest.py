"""Shared test fixtures for reins tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from reinicorn.git import run_git

# Git 2.38+ blocks local file transport by default (CVE-2022-39253).
# All test repos use local paths. Set at module level so it's inherited
# by all subprocess.run() calls before any fixtures run.
os.environ["GIT_ALLOW_PROTOCOL"] = "file:ext:https:http:ssh:git"


def _git_init(path: Path) -> None:
    """Init a git repo with test user config."""
    run_git("init", "-q", "-b", "main", str(path))
    run_git("config", "user.email", "test@test.com", cwd=path)
    run_git("config", "user.name", "Test User", cwd=path)


def _git_commit(path: Path, message: str = "initial") -> None:
    """Stage all and commit."""
    run_git("add", "-A", cwd=path)
    run_git("commit", "-q", "-m", message, cwd=path)


@pytest.fixture
def kb_repo(tmp_path: Path) -> Path:
    """Create an isolated git repo with a minimal kb structure.

    Returns the repo root path.  The repo has one commit so that git
    operations (branch, log, etc.) work correctly.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)

    # Minimal kb structure
    kb = repo / "kb"
    kb.mkdir()

    # Repo-scoped structure
    repo_sub = kb / "testproject"
    repo_sub.mkdir()
    (repo_sub / "exec-plans").mkdir()
    (repo_sub / "exec-plans" / "active").mkdir()
    (repo_sub / "exec-plans" / "_template").mkdir()

    # Template files
    (repo_sub / "exec-plans" / "_template" / "plan.md").write_text(
        "# Execution Plan: [Branch Name]\n\n"
        "**Author:** [developer or agent]\n"
        "**Date:** [date]\n"
        "**Ticket:** [TICKET-ID or N/A]\n"
        "**Status:** [planning | in-progress | complete | abandoned]\n\n"
        "## Goal\n\n## Acceptance Criteria\n\n## Tasks\n"
    )
    (repo_sub / "exec-plans" / "_template" / "progress.md").write_text(
        "# Progress\n"
    )
    (repo_sub / "exec-plans" / "_template" / "decisions.md").write_text(
        "# Decisions\n"
    )

    # .gitmodules so get_kb_dir() resolves to kb/
    (repo / ".gitmodules").write_text(
        '[submodule "kb"]\n'
        '    path = kb\n'
        '    url = fake-for-tests\n'
    )

    # Config
    (repo / ".reinicorn-config").write_text(
        'REINICORN_TICKET_PATTERN="[A-Z]+-[0-9]+"\n'
        "REINICORN_STALE_THRESHOLD=30\n"
        "REINICORN_AUTO_SYNC=true\n"
        "REINICORN_AGENT_CMD='echo {prompt}'\n"
    )

    # Linters config
    linters = repo / "linters"
    linters.mkdir()
    (linters / ".lint-config.json").write_text(
        '{"rules": {'
        '"kb/docs-freshness": {"enabled": true, "severity": "warning", "max_days_stale": 30},'
        '"kb/cross-links": {"enabled": true, "severity": "error"},'
        '"kb/plan-structure": {"enabled": true, "severity": "warning"}'
        "}}"
    )

    _git_commit(repo)
    return repo


@pytest.fixture
def kb_pair(tmp_path: Path) -> tuple[Path, Path]:
    """(bare_remote, local_kb) — local cloned from bare, one commit on main.

    Contains one spec draft at myrepo/specs/drafts/x.md.
    """
    bare = tmp_path / "kb-remote.git"
    run_git("init", "-q", "--bare", "-b", "main", str(bare))
    local = tmp_path / "kb"
    run_git("clone", "-q", str(bare), str(local))
    run_git("config", "user.email", "test@test.com", cwd=local)
    run_git("config", "user.name", "Test User", cwd=local)
    run_git("config", "protocol.file.allow", "always", cwd=local)
    d = local / "myrepo" / "specs" / "drafts"
    d.mkdir(parents=True)
    (d / "x.md").write_text("# X\n\n**Status:** draft\n\n## Problem\n\nbody\n")
    _git_commit(local, "init")
    run_git("push", "-q", "origin", "main", cwd=local)
    return bare, local


@pytest.fixture
def submodule_repo(tmp_path: Path) -> Path:
    """Create a parent repo with a real kb submodule on main branch.

    Returns the parent repo root. The submodule has a remote at
    tmp_path/kb-remote that can be used for push/fetch tests.
    """
    # Create a staging repo, then clone it bare as the "remote"
    staging = tmp_path / "kb-staging"
    staging.mkdir()
    _git_init(staging)
    (staging / "README.md").write_text("# Kb\n")
    _git_commit(staging, "init")

    remote = tmp_path / "kb-remote"
    run_git(
        "-c", "protocol.file.allow=always",
        "clone", "--bare", str(staging), str(remote),
    )

    # Create the parent repo with kb as submodule
    parent = tmp_path / "parent"
    parent.mkdir()
    _git_init(parent)
    run_git(
        "-c", "protocol.file.allow=always",
        "submodule", "add", str(remote), "kb",
        cwd=parent,
    )
    _git_commit(parent, "init")

    # Configure the submodule for CI (no global git config on runners):
    # - user identity (required for commits)
    # - protocol.file.allow (git 2.38+ blocks local file transport)
    kb = parent / "kb"
    run_git("config", "user.email", "test@test.com", cwd=kb)
    run_git("config", "user.name", "Test User", cwd=kb)
    run_git("config", "protocol.file.allow", "always", cwd=kb)

    # Put kb on main branch (not detached HEAD)
    r = run_git("checkout", "-q", "main", cwd=kb, check=False)
    if r.returncode != 0:
        run_git("checkout", "-q", "-b", "main", cwd=kb)

    return parent
