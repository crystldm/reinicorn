"""Centralized git subprocess interface.

Every module that needs git goes through run_git().  This gives tests a
single mock-point.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# Git env vars that override cwd-based repo discovery. When a git hook invokes
# reinicorn, git sets these to point at the *invoking* worktree's gitdir — so any
# `run_git(..., cwd=submodule_dir)` would silently target the parent gitdir
# instead. Strip them so subprocess git rediscovers the repo from cwd.
_GIT_DISCOVERY_ENV_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
)


def run_git(
    *args: str,
    capture: bool = True,
    check: bool = True,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the CompletedProcess."""
    env = {k: v for k, v in os.environ.items() if k not in _GIT_DISCOVERY_ENV_VARS}
    return subprocess.run(
        ["git", *args],
        capture_output=capture,
        text=True,
        check=check,
        cwd=cwd,
        env=env,
    )


def repo_root(quiet: bool = False) -> Path | None:
    """Return the repo root as a Path, or None if not in a repo.

    If the cwd is inside a git submodule (e.g. the kb), walks up
    to the superproject root so that reinicorn commands resolve paths
    against the real project, not the submodule.
    """
    try:
        r = run_git("rev-parse", "--show-toplevel")
        root = Path(r.stdout.strip())

        # Detect submodule: if a superproject exists, use that instead.
        sp = run_git("rev-parse", "--show-superproject-working-tree", check=False)
        if sp.returncode == 0 and sp.stdout.strip():
            root = Path(sp.stdout.strip())

        return root
    except (subprocess.CalledProcessError, FileNotFoundError):
        if not quiet:
            from reinicorn.console import error
            error("Not inside a git repository.")
        return None


def current_branch() -> str:
    """Return the current branch name, or '' if detached."""
    try:
        r = run_git("symbolic-ref", "--short", "HEAD")
        return r.stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def remote_url(cwd: Path | None = None) -> str:
    """The 'origin' remote URL, or '' if unset/not a git repo."""
    r = run_git("remote", "get-url", "origin", check=False, cwd=cwd)
    return r.stdout.strip() if r.returncode == 0 else ""


def gh_repo_from_url(url: str) -> str | None:
    """'owner/name' from a github.com remote URL (ssh or https), else None."""
    m = re.match(
        r"(?:git@github\.com:|https://github\.com/)([^/]+/[^/]+?)(?:\.git)?/?$",
        url.strip(),
    )
    return m.group(1) if m else None


def file_transport_args(cwd: Path | None = None) -> tuple[str, ...]:
    """Return ('-c', 'protocol.file.allow=always') if the origin remote is a local path.

    Git 2.38+ (CVE-2022-39253) blocks local file transport by default.
    This affects clone, submodule add, fetch, and push to local paths.
    The -c flag is the only reliable method — local/global git config is
    ignored for protocol restrictions on git 2.52+.
    """
    try:
        url = remote_url(cwd)
        if url.startswith("/") or url.startswith("file://"):
            return ("-c", "protocol.file.allow=always")
    except FileNotFoundError:
        pass
    return ()


def scratch_clone(
    url: str, dest: Path, *, transport: tuple[str, ...] = (),
    depth1: bool = False, ident: str = "reinicorn",
) -> Path:
    """Clone into a scratch dir for commit+push work, git user configured.

    gc.auto=0 / maintenance.auto=false: background git maintenance in the
    temp clone would race the TemporaryDirectory cleanup (rmtree fails with
    "Directory not empty" when gc recreates files under .git/objects).
    """
    depth = ("--depth", "1") if depth1 else ()
    run_git(
        *transport, "clone", "-q", *depth,
        "-c", "gc.auto=0", "-c", "maintenance.auto=false",
        url, str(dest),
    )
    run_git("config", "user.email", f"reinicorn@{ident}", cwd=dest)
    run_git("config", "user.name", f"Reinicorn {ident.capitalize()}", cwd=dest)
    return dest


def reinicorn_root() -> Path:
    """Return the Reinicorn installation root (parent of src/)."""
    return Path(__file__).resolve().parent.parent.parent


def sanitize_branch(name: str) -> str:
    """Sanitize a branch name for use as a directory name.

    Replaces '/' with '-' so that 'feature/mvp' becomes 'feature-mvp',
    avoiding nested directories in exec-plan paths.
    """
    return name.replace("/", "-")


def remote_uses_ssh(cwd: Path | None = None) -> bool:
    """Check if the origin remote uses SSH (git@...) rather than HTTPS."""
    try:
        root = cwd or repo_root(quiet=True)
        if root is None:
            return False
        return remote_url(root).startswith("git@")
    except Exception:
        return False


def https_to_ssh(url: str) -> str:
    """Convert an HTTPS GitHub URL to SSH format.

    https://github.com/owner/repo → git@github.com:owner/repo.git
    """
    m = re.match(r"https://([^/]+)/(.+?)(?:\.git)?$", url)
    if m:
        host, path = m.group(1), m.group(2)
        return f"git@{host}:{path}.git"
    return url


def repo_slug() -> str:
    """Derive the repo name from the git remote origin URL.

    Examples:
        git@github.com:acme/reinicorn.git → "reinicorn"
        https://github.com/acme/reinicorn.git → "reinicorn"

    Returns "unknown" if no remote is configured.
    Uses repo_root() as cwd so that running from inside a submodule
    (e.g. the kb) resolves the parent project's remote, not the
    submodule's.
    """
    try:
        root = repo_root(quiet=True)
        if root is None:
            return "unknown"
        url = remote_url(root)
        if not url:
            return "unknown"
        # Strip trailing .git
        if url.endswith(".git"):
            url = url[:-4]
        # Take the last path component
        return url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    except Exception:
        return "unknown"
