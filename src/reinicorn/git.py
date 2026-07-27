"""Centralized git subprocess interface.

Every module that needs git goes through run_git().  This gives tests a
single mock-point.

This module also owns every git-failure→message conversion. Reading
`.stderr` off a git result is confined here (enforced by
tests/test_git_error_surface.py): callers describe *what they were doing* and
hand the failure to `explain_failure`/`report_failure`, which classify it and
always print git's own words. Six modules used to invent their own shape, and
one of them substituted a guess ("kb has conflicting changes") for an
authentication error — the guess cost more than no diagnosis would have,
because agents act on it.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

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


class GitError(subprocess.CalledProcessError):
    """A git command that was expected to succeed did not.

    Subclasses CalledProcessError on purpose: the error contract documented in
    review.py ("local git operations may raise subprocess.CalledProcessError")
    keeps holding for every existing handler, while new code can catch the
    narrower type. cmd/returncode/stdout/stderr come from the base class.
    """


def run_git(
    *args: str,
    capture: bool = True,
    check: bool = True,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the CompletedProcess.

    Raises GitError when *check* is set and git fails.
    """
    env = {k: v for k, v in os.environ.items() if k not in _GIT_DISCOVERY_ENV_VARS}
    r = subprocess.run(
        ["git", *args],
        capture_output=capture,
        text=True,
        check=False,
        cwd=cwd,
        env=env,
    )
    if check and r.returncode != 0:
        raise GitError(r.returncode, ["git", *args], r.stdout, r.stderr)
    return r


# --------------------------------------------------------------------------
# The one git-failure→message seam
# --------------------------------------------------------------------------

#: Either shape a failed git call arrives in: a result the caller chose not to
#: check, or the GitError raised when it did.
GitFailure = subprocess.CompletedProcess[str] | subprocess.CalledProcessError

# Ordered by precedence, not by likelihood. Auth is checked first because a
# credential failure is often reported alongside a rejected ref, and it is the
# diagnosis that changes what the user should do next.
_AUTH_MARKERS = (
    "could not read username",
    "could not read password",
    "permission denied (publickey)",
    "authentication failed",
    "invalid username or password",
    "terminal prompts disabled",
)
_NON_FF_MARKERS = ("non-fast-forward", "fetch first")
_PROTECTED_MARKERS = ("gh006", "protected branch")

# Domain-free on purpose: this module knows git, not the kb. Callers add their
# own detail lines for what the failure means in their vocabulary.
_HEADLINES = {
    "auth": "the remote rejected authentication",
    "non-fast-forward": "the remote has commits this push does not contain",
    "protected": "the branch is protected and rejected a direct push",
}


def classify_failure(stderr: str) -> str:
    """Why git failed: 'auth', 'non-fast-forward', 'protected', or 'unknown'.

    'unknown' is a real answer, not a bucket to guess from — callers must show
    git's own output for it rather than substituting a plausible cause.
    """
    text = (stderr or "").lower()
    if any(m in text for m in _AUTH_MARKERS):
        return "auth"
    if any(m in text for m in _NON_FF_MARKERS):
        return "non-fast-forward"
    if any(m in text for m in _PROTECTED_MARKERS):
        return "protected"
    return "unknown"


def _stderr_of(
    failure: subprocess.CompletedProcess[str] | subprocess.CalledProcessError,
) -> str:
    """git's stderr from either result shape. The only read of it in the tree."""
    return (getattr(failure, "stderr", None) or "").strip()


def classify_result(
    failure: subprocess.CompletedProcess[str] | subprocess.CalledProcessError,
) -> str:
    """classify_failure() for a git result, so callers never touch stderr."""
    return classify_failure(_stderr_of(failure))


def url_protocol(url: str) -> str:
    """The transport a remote URL uses: 'https', 'ssh', 'local', or 'unknown'."""
    if url.startswith(("https://", "http://")):
        return "https"
    if url.startswith("ssh://") or (url and "@" in url.split("/")[0]):
        return "ssh"
    if url.startswith(("file://", "/")):
        return "local"
    return "unknown"


def explain_failure(
    action: str,
    failure: subprocess.CompletedProcess[str] | subprocess.CalledProcessError,
    *,
    detail: Sequence[str] = (),
) -> list[str]:
    """Render a git failure as lines: headline, caller detail, then git.

    *action* is what the caller was trying to do, phrased to follow "Could not"
    ("push kb main", "merge origin/main"). Every line of git's stderr is
    reproduced under a `git:` prefix — nothing is summarized away, and an
    unclassifiable failure gets no invented cause at all.
    """
    stderr = _stderr_of(failure)
    kind = classify_failure(stderr)
    reason = _HEADLINES.get(kind)
    if reason is None:
        rc = getattr(failure, "returncode", 1)
        reason = f"git exited {rc} and Reinicorn cannot classify why"
    lines = [f"Could not {action} — {reason}."]
    lines.extend(f"  {d}" for d in detail)
    lines.extend(f"  git: {line}" for line in stderr.splitlines())
    return lines


def report_failure(
    action: str,
    failure: subprocess.CompletedProcess[str] | subprocess.CalledProcessError,
    *,
    detail: Sequence[str] = (),
    warn: bool = False,
) -> str:
    """Print explain_failure() and return the classification.

    Callers add their own `console.next_step(...)` from the returned kind: the
    seam owns *what went wrong*, the caller owns *what to run next*, because
    only the caller knows its command vocabulary.
    """
    from reinicorn import console

    lines = explain_failure(action, failure, detail=detail)
    emit = console.warn if warn else console.error
    emit(lines[0])
    for line in lines[1:]:
        console.info(line)
    return classify_result(failure)


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

    Replaces '/' and '\' with '-' so that 'feature/mvp' becomes
    'feature-mvp', avoiding nested directories in exec-plan paths.
    Path-traversal names ('.', '..', empty) collapse to '-' so the
    result can never escape its parent directory.
    """
    safe = name.replace("/", "-").replace("\\", "-")
    if safe in ("", ".", ".."):
        return "-"
    return safe


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
