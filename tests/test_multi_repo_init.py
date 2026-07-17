"""Test that reins init creates repo-scoped dir for non-empty kbs."""

from __future__ import annotations

from pathlib import Path

from reinicorn.commands.init import cmd_init
from reinicorn.git import run_git


def _git(*args: str, cwd: Path | None = None) -> None:
    run_git(*args, cwd=cwd)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=path)
    _git("config", "user.email", "test@test", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    _git("commit", "--allow-empty", "-m", "init", cwd=path)


def test_multi_repo_init_creates_scope_dir(tmp_path: Path):
    """When a second repo inits against a non-empty kb, its repo-scoped dir is created."""
    # Set up a bare kb remote with repo-a content already present
    bare = tmp_path / "kb.git"
    bare.mkdir()
    _git("init", "--bare", "-q", cwd=bare)

    # Seed the kb with repo-a scope (simulating a first repo's init)
    seed = tmp_path / "seed"
    _git(
        "-c", "protocol.file.allow=always",
        "clone", "-q", str(bare), str(seed),
    )
    _git("config", "user.email", "test@test", cwd=seed)
    _git("config", "user.name", "Test", cwd=seed)

    from reinicorn.kb_seed import generate_seed_tree
    generate_seed_tree(seed, "repo-a")
    _git("add", "-A", cwd=seed)
    _git("commit", "-q", "-m", "seed repo-a", cwd=seed)
    _git(
        "-c", "protocol.file.allow=always",
        "push", "-q", "origin", "HEAD",
        cwd=seed,
    )

    # Now create repo-b and run init against the same kb
    repo_b = tmp_path / "repo-b"
    _init_repo(repo_b)

    from unittest.mock import patch
    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="repo-b"), \
         patch("reinicorn.commands.init._prompt_platforms", return_value=["claude"]):
        rc = cmd_init(kb_url=str(bare), cwd=repo_b)

    assert rc == 0

    # The kb submodule should contain repo-b's scoped directory
    kb_dir = repo_b / "kb"
    assert kb_dir.is_dir()
    assert (kb_dir / "repo-b").is_dir(), "repo-b scope dir should exist in kb"
    assert (kb_dir / "repo-b" / "golden-principles.md").is_file()
    assert (kb_dir / "repo-b" / "README.md").read_text().startswith(
        "# repo-b knowledge base\n"
    )


def test_multi_repo_init_idempotent(tmp_path: Path):
    """Running init twice against a non-empty kb does not fail or duplicate content."""
    bare = tmp_path / "kb.git"
    bare.mkdir()
    _git("init", "--bare", "-q", cwd=bare)

    # Seed kb with repo-a scope
    seed = tmp_path / "seed"
    _git(
        "-c", "protocol.file.allow=always",
        "clone", "-q", str(bare), str(seed),
    )
    _git("config", "user.email", "test@test", cwd=seed)
    _git("config", "user.name", "Test", cwd=seed)

    from reinicorn.kb_seed import generate_seed_tree
    generate_seed_tree(seed, "repo-a")
    _git("add", "-A", cwd=seed)
    _git("commit", "-q", "-m", "seed repo-a", cwd=seed)
    _git(
        "-c", "protocol.file.allow=always",
        "push", "-q", "origin", "HEAD",
        cwd=seed,
    )

    repo_b = tmp_path / "repo-b"
    _init_repo(repo_b)

    from unittest.mock import patch
    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="repo-b"), \
         patch("reinicorn.commands.init._prompt_platforms", return_value=["claude"]):
        rc1 = cmd_init(kb_url=str(bare), cwd=repo_b)

    assert rc1 == 0
    assert (repo_b / "kb" / "repo-b").is_dir()

    # Run init again — should succeed without errors
    with patch("reinicorn.commands.init.cmd_hooks_install", return_value=0), \
         patch("reinicorn.commands.init.repo_slug", return_value="repo-b"), \
         patch("reinicorn.commands.init._prompt_platforms", return_value=["claude"]):
        rc2 = cmd_init(kb_url=str(bare), cwd=repo_b)

    assert rc2 == 0
    assert (repo_b / "kb" / "repo-b" / "golden-principles.md").is_file()
