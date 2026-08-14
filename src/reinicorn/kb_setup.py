"""Kb clone setup with empty-remote detection and cleanup.

Handles the common failure modes from init/attach:
- Empty/bare remotes (no commits) — detect and seed automatically
- Failed clone leaves stale state — clean up properly
- Opaque git errors — surface stderr in error messages
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from reinicorn import console
from reinicorn.config import KB_DIR_NAME
from reinicorn.git import GitError, explain_failure, run_git, scratch_clone
from reinicorn.kb_seed import generate_seed_tree
from reinicorn.validation import validate_git_url


class KbSetupError(Exception):
    """Raised when kb clone setup fails.

    The message carries the whole diagnosis, git's own output included — built
    by `git.explain_failure`, never assembled here. Nothing outside git.py
    reads a git result's stderr (see tests/test_git_error_surface.py).
    """


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


def cleanup_failed_kb(target_dir: Path) -> None:
    """Remove stale state from a failed kb clone attempt.

    Cleans both kb/ directory and .git/modules/kb — the latter can be left
    behind by a migration or an old submodule-era checkout, and a fresh clone
    must not trip on it.
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


def ensure_kb_gitignored(root: Path) -> bool:
    """Add `kb/` to the repo .gitignore. Returns True when it was added."""
    gitignore = root / ".gitignore"
    entry = f"{KB_DIR_NAME}/"
    existing = gitignore.read_text() if gitignore.is_file() else ""
    if entry in existing.splitlines():
        return False
    text = existing if existing.endswith("\n") or not existing else existing + "\n"
    gitignore.write_text(text + entry + "\n")
    return True


def setup_kb_clone(
    target_dir: Path,
    url: str,
    repo_slug: str | None = None,
) -> bool:
    """Clone kb as a plain, gitignored git clone with proper error handling.

    - Detects and seeds empty remotes
    - Cleans up stale state from prior failed attempts
    - Surfaces git stderr in error messages
    """
    url_error = validate_git_url(url)
    if url_error is not None:
        raise KbSetupError(
            f"Refusing to use kb URL '{url}'.\n"
            f"  {url_error}\n"
            f"  How to fix: use an https://, ssh://, git@host:path, or local URL."
        )

    kb_dir = target_dir / KB_DIR_NAME

    # Clean up any stale state from prior failed attempts
    if kb_dir.is_dir() and not (kb_dir / ".git").exists():
        console.info("Cleaning up stale state from a previous failed setup...")
        cleanup_failed_kb(target_dir)

    # Check if remote is empty and seed if needed
    if is_remote_empty(url):
        if repo_slug is None:
            from reinicorn.git import repo_slug as get_slug
            repo_slug = get_slug()
        try:
            seed_remote(url, repo_slug)
        except GitError as e:
            # Callers catch KbSetupError, not GitError — an unconverted
            # seeding failure surfaces as a raw traceback.
            raise KbSetupError("\n".join(explain_failure(
                "seed the empty kb remote", e,
                detail=[f"URL: {url}"],
            ))) from e

    file_allow = ("-c", "protocol.file.allow=always") if url.startswith("/") else ()
    r = run_git(*file_allow, "clone", url, str(kb_dir), check=False)
    if r.returncode != 0:
        cleanup_failed_kb(target_dir)
        raise KbSetupError("\n".join(explain_failure(
            "clone the kb", r,
            detail=[
                f"URL: {url}",
                "How to fix: Check the URL is correct and you have access.",
            ],
        )))

    ensure_kb_gitignored(target_dir)
    console.success("Kb cloned (tracking main)")
    return True
