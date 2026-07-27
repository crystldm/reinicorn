"""Resolve the origin URL a kb clone should use.

The kb's remote is recorded in three places that can disagree: the clone the
user actually works in, `REINICORN_KB_REMOTE` in `.reinicorn-config`, and (while
the kb is still a submodule) `.gitmodules`. Only the first reflects local
overrides — an SSH rewrite, an internal mirror — so a kb created for a new
worktree or a fresh clone must prefer it. Falling back to a recorded URL means
falling back to a *protocol* the user may not be able to authenticate with,
which is why the recorded value is adapted to the protocol `gh` reports for the
host before it is used.

This module is the single seam for that decision. Nothing here is
submodule-specific except `_gitmodules_url`, which is explicitly the last
fallback and goes away with the submodule.
"""

from __future__ import annotations

from pathlib import Path

from reinicorn import console
from reinicorn.config import KB_DIR_NAME, config_get
from reinicorn.git import gh_repo_from_url, https_to_ssh, remote_url, run_git
from reinicorn.github import run_gh
from reinicorn.validation import validate_git_url

KB_REMOTE_KEY = "REINICORN_KB_REMOTE"
GITHUB_HOST = "github.com"


def git_protocol_preference(host: str = GITHUB_HOST) -> str:
    """The git protocol `gh` is configured to use for *host*: 'ssh', 'https', ''.

    Queried host-scoped on purpose. `gh config get git_protocol` returns the
    global default from `config.yml`, which the per-host value in `hosts.yml`
    overrides — a machine can read 'https' globally while every github.com
    operation genuinely uses ssh. Returns '' when gh is absent or has no answer,
    which callers must treat as "no evidence", not as a protocol.
    """
    try:
        r = run_gh("config", "get", "-h", host, "git_protocol", check=False)
    except RuntimeError:  # gh not installed
        return ""
    if r.returncode != 0:
        return ""
    value = (r.stdout or "").strip().lower()
    return value if value in ("ssh", "https") else ""


def adapt_url_to_git_protocol(url: str) -> str:
    """Rewrite a GitHub HTTPS URL to its SSH form when gh says the host uses ssh.

    Deliberately one-way. `gh` reports 'https' for any host it has no explicit
    entry for, so "gh said https" is not evidence that HTTPS works — rewriting
    SSH to HTTPS on that basis would break every ssh-only user. Rewriting the
    other way needs a positive, user-set 'ssh' preference, and HTTPS with a
    credential helper is left untouched.
    """
    if not url.startswith("https://"):
        return url
    if gh_repo_from_url(url) is None:  # not github.com; gh's answer says nothing
        return url
    if git_protocol_preference() != "ssh":
        return url
    return https_to_ssh(url)


def _main_checkout_root(root: Path) -> Path:
    """The main checkout's root — *root* itself outside a linked worktree.

    Linked worktrees share `<main>/.git` as their common dir, so its parent is
    the main checkout. Layouts where that does not hold (bare repos,
    `--separate-git-dir`) fall back to *root*; the caller only reads a kb
    directory from the result, so a wrong guess degrades to "nothing inherited".
    """
    r = run_git("rev-parse", "--git-common-dir", cwd=root, check=False)
    if r.returncode != 0 or not r.stdout.strip():
        return root
    common = Path(r.stdout.strip())
    if not common.is_absolute():
        common = root / common
    return common.resolve().parent


def inherited_kb_remote_url(root: Path) -> str:
    """`remote.origin.url` of an existing kb clone, or '' if there is none.

    Checks this checkout's kb first, then the main checkout's — a new worktree
    has no kb yet, and the main checkout's is where a local override lives.
    """
    for candidate in (root, _main_checkout_root(root)):
        kb_dir = candidate / KB_DIR_NAME
        if not (kb_dir / ".git").exists():
            continue
        url = remote_url(kb_dir)
        if url:
            return url
    return ""


def _gitmodules_url(root: Path) -> str:
    """The kb `url =` from `.gitmodules`, or ''.

    Transitional: the last fallback for repos that predate
    `REINICORN_KB_REMOTE`. Removed with the submodule.
    """
    gitmodules = root / ".gitmodules"
    if not gitmodules.is_file():
        return ""
    in_kb_section = False
    for line in gitmodules.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_kb_section = stripped == f'[submodule "{KB_DIR_NAME}"]'
            continue
        if in_kb_section:
            key, _, value = stripped.partition("=")
            if key.strip() == "url":
                return value.strip()
    return ""


def configured_kb_remote_url(root: Path) -> str:
    """The kb remote as *recorded* by the repo, without protocol adaptation."""
    return config_get(KB_REMOTE_KEY, root=root) or _gitmodules_url(root)


def resolve_kb_remote_url(root: Path) -> str:
    """The URL a kb clone under *root* should use for origin, or ''.

    Order: an existing kb clone's origin (this checkout, then the main
    checkout), then the recorded URL adapted to the user's git protocol. An
    inherited URL is used verbatim — it is already the user's working
    configuration, and second-guessing its protocol would undo a deliberate
    override.
    """
    inherited = inherited_kb_remote_url(root)
    if inherited:
        return inherited
    configured = configured_kb_remote_url(root)
    if not configured:
        return ""
    return adapt_url_to_git_protocol(configured)


def apply_kb_remote_url(kb_dir: Path, url: str) -> bool:
    """Point *kb_dir*'s origin at *url*. Returns True if the remote changed.

    *url* can originate in `.gitmodules`, which is repository-controlled, so it
    is validated before it reaches git — the same reason `get_kb_dir()` guards
    the submodule path.
    """
    if not url:
        return False
    url_error = validate_git_url(url)
    if url_error is not None:
        console.error(
            f"Refusing kb remote URL '{url}': {url_error}\n"
            f"  How to fix: set {KB_REMOTE_KEY} in .reinicorn-config to an "
            f"https://, ssh://, git@host:path, or local URL."
        )
        return False
    current = remote_url(kb_dir)
    if current == url:
        return False
    verb = "set-url" if current else "add"
    r = run_git("remote", verb, "origin", url, cwd=kb_dir, check=False)
    return r.returncode == 0
