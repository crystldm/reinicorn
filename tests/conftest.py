"""Shared test fixtures for reins tests."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from reinicorn import frontmatter
from reinicorn.git import run_git


def doc_text(body: str = "\n## Problem\n\nbody\n", **meta) -> str:
    """A valid frontmatter doc for fixtures.

    One definition of the on-disk shape, so a schema change touches this
    helper rather than every test that happens to write a doc.
    """
    base: dict = {
        "type": "spec", "title": "X", "slug": "x",
        "lifecycle": frontmatter.LIFECYCLE_ACTIVE,
        "status": frontmatter.STATUS_DRAFT,
        "created": date(2026, 7, 27), "author": "Test User",
        "origin": frontmatter.ORIGIN_AI, "human_validated": False,
    }
    base.update(meta)
    assert not frontmatter.validate(base), frontmatter.validate(base)
    return frontmatter.dumps(base, body)

# Git 2.38+ blocks local file transport by default (CVE-2022-39253).
# All test repos use local paths. Set at module level so it's inherited
# by all subprocess.run() calls before any fixtures run.
os.environ["GIT_ALLOW_PROTOCOL"] = "file:ext:https:http:ssh:git"


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Each test sees the registry as this test's cwd/patches define it.

    `doc_types.registry()` memoizes per process; tests chdir between tmp
    repos and patch the defaults dict, so a warm cache would leak one
    test's effective registry into the next.
    """
    from reinicorn.doc_types import _reset_registry_cache
    _reset_registry_cache()
    yield
    _reset_registry_cache()


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
        "---\n"
        "type: plan\n"
        "title: 'Execution Plan: [Branch Name]'\n"
        "slug: '[Branch Name]'\n"
        "lifecycle: active\n"
        "status: planning\n"
        "created: [date]\n"
        "author: '[developer or agent]'\n"
        "branch: '[Branch Name]'\n"
        "ticket: '[TICKET-ID or N/A]'\n"
        "---\n\n"
        "# Execution Plan: [Branch Name]\n\n"
        "## Goal\n\n## Acceptance Criteria\n\n## Tasks\n"
    )
    (repo_sub / "exec-plans" / "_template" / "progress.md").write_text(
        "# Progress\n"
    )
    (repo_sub / "exec-plans" / "_template" / "decisions.md").write_text(
        "# Decisions\n"
    )

    # kb/ is a plain nested git repo, gitignored by the parent (clone layout)
    _git_init(kb)
    (repo / ".gitignore").write_text("kb/\n")
    _git_commit(kb, "kb init")

    # Config
    (repo / ".reinicorn-config").write_text(
        'REINICORN_TICKET_PATTERN="[A-Z]+-[0-9]+"\n'
        "REINICORN_STALE_THRESHOLD=30\n"
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
    (d / "x.md").write_text(doc_text())
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


@pytest.fixture
def kb_clone_repo(tmp_path: Path) -> Path:
    """Parent repo with kb/ as an ordinary clone of a local bare remote.

    The clone layout every kb-operation test uses. The remote lives at
    tmp_path/kb-remote for push/fetch assertions; `submodule_repo` remains
    only for migration tests.
    """
    staging = tmp_path / "kb-staging"
    staging.mkdir()
    _git_init(staging)
    (staging / "README.md").write_text("# Kb\n")
    _git_commit(staging, "init")

    remote = tmp_path / "kb-remote"
    run_git("-c", "protocol.file.allow=always",
            "clone", "--bare", str(staging), str(remote))

    parent = tmp_path / "parent"
    parent.mkdir()
    _git_init(parent)
    (parent / ".gitignore").write_text("kb/\n")
    (parent / ".reinicorn-config").write_text(
        f'REINICORN_KB_REMOTE="{remote}"\n'
    )
    _git_commit(parent, "init")

    run_git("-c", "protocol.file.allow=always",
            "clone", str(remote), str(parent / "kb"))
    kb = parent / "kb"
    run_git("config", "user.email", "test@test.com", cwd=kb)
    run_git("config", "user.name", "Test User", cwd=kb)
    run_git("config", "protocol.file.allow", "always", cwd=kb)
    return parent
