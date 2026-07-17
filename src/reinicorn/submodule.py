"""Submodule setup with empty-remote detection and cleanup.

Handles the common failure modes from init/attach:
- Empty/bare remotes (no commits) — detect and seed automatically
- Failed submodule add leaves stale state — clean up properly
- Opaque git errors — surface stderr in error messages
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from reinicorn import console
from reinicorn.config import KB_DIR_NAME
from reinicorn.git import run_git, scratch_clone
from reinicorn.kb_seed import generate_seed_tree
from reinicorn.validation import validate_git_url


class SubmoduleError(Exception):
    """Raised when submodule setup fails with diagnostic info."""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


def is_remote_empty(url: str) -> bool:
    """Check if a git remote has no refs (bare/empty)."""
    file_allow = ("-c", "protocol.file.allow=always") if url.startswith("/") else ()
    r = run_git(*file_allow, "ls-remote", url, check=False)
    return r.returncode == 0 and not r.stdout.strip()


def seed_remote(url: str, repo_slug: str) -> None:
    """Push a clean kb template to an empty remote."""
    console.info("Remote is empty — seeding with clean kb template...")
    file_allow = ("-c", "protocol.file.allow=always") if url.startswith("/") else ()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_path = scratch_clone(
            url, Path(tmp) / "kb-seed", transport=file_allow, ident="init",
        )
        generate_seed_tree(tmp_path, repo_slug)
        run_git("add", "-A", cwd=tmp_path)
        run_git("commit", "-q", "-m", "chore: initialize reinicorn kb", cwd=tmp_path)
        run_git(*file_allow, "push", "-q", "origin", "HEAD", cwd=tmp_path)

    console.success(f"Seeded remote with kb template for '{repo_slug}'")


def cleanup_failed_submodule(target_dir: Path) -> None:
    """Remove stale state from a failed submodule add.

    Cleans both kb/ directory and .git/modules/kb.
    """
    kb = target_dir / KB_DIR_NAME
    if kb.exists():
        shutil.rmtree(kb)

    modules = target_dir / ".git" / "modules" / KB_DIR_NAME
    if modules.exists():
        shutil.rmtree(modules)

    # Remove kb entry from .git/config if present
    run_git("config", "--remove-section", f"submodule.{KB_DIR_NAME}",
            check=False, cwd=target_dir)


def setup_submodule(
    target_dir: Path,
    url: str,
    repo_slug: str | None = None,
) -> bool:
    """Add kb as a git submodule with proper error handling.

    - Detects and seeds empty remotes
    - Cleans up stale state from prior failed attempts
    - Surfaces git stderr in error messages
    """
    url_error = validate_git_url(url)
    if url_error is not None:
        raise SubmoduleError(
            f"Refusing to use kb URL '{url}'.\n"
            f"  {url_error}\n"
            f"  How to fix: use an https://, ssh://, git@host:path, or local URL."
        )

    kb_dir = target_dir / KB_DIR_NAME

    # Clean up any stale state from prior failed attempts
    if kb_dir.is_dir() and not (target_dir / ".gitmodules").is_file():
        console.info("Cleaning up stale state from a previous failed setup...")
        cleanup_failed_submodule(target_dir)

    # Check if remote is empty and seed if needed
    if is_remote_empty(url):
        if repo_slug is None:
            from reinicorn.git import repo_slug as get_slug
            repo_slug = get_slug()
        seed_remote(url, repo_slug)

    # Add submodule
    file_allow = ("-c", "protocol.file.allow=always") if url.startswith("/") else ()
    r = run_git(
        *file_allow,
        "submodule", "add", url, KB_DIR_NAME,
        check=False, cwd=target_dir,
    )

    if r.returncode != 0:
        # Check if already registered
        gitmodules = target_dir / ".gitmodules"
        if gitmodules.is_file() and KB_DIR_NAME in gitmodules.read_text():
            console.warn("Kb submodule already registered — updating")
            run_git(*file_allow, "submodule", "update", "--init", KB_DIR_NAME, cwd=target_dir)
        else:
            cleanup_failed_submodule(target_dir)
            raise SubmoduleError(
                f"Failed to add kb submodule.\n"
                f"  URL: {url}\n"
                f"  Git error: {r.stderr.strip()}\n"
                f"  How to fix: Check the URL is correct and you have access.",
                stderr=r.stderr,
            )

    # Configure submodule
    run_git("config", "-f", ".gitmodules", f"submodule.{KB_DIR_NAME}.branch", "main",
            check=False, cwd=target_dir)
    run_git("config", "-f", ".gitmodules", f"submodule.{KB_DIR_NAME}.ignore", "all",
            check=False, cwd=target_dir)

    console.success("Kb added as submodule tracking main branch (ignore=all)")
    return True
