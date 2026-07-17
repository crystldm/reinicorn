"""Boundary validation for user-supplied names and identifiers."""

from __future__ import annotations

import re

# Alphanumeric, hyphens, underscores, dots. Must start with alphanumeric.
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


VALID_GIT_HOOKS = frozenset({
    "applypatch-msg", "pre-applypatch", "post-applypatch",
    "pre-commit", "pre-merge-commit", "prepare-commit-msg", "commit-msg", "post-commit",
    "pre-rebase", "post-checkout", "post-merge", "pre-push",
    "pre-receive", "update", "proc-receive", "post-receive", "post-update",
    "reference-transaction", "push-to-checkout", "pre-auto-gc",
    "post-rewrite", "sendemail-validate", "fsmonitor-watchman",
    "p4-changelist", "p4-prepare-changelist", "p4-post-changelist", "p4-pre-submit",
    "post-index-change",
})


def validate_hook_name(name: str) -> str:
    """Validate that a hook name is a recognized git hook.

    Returns the name unchanged if valid.
    Raises ValueError if the name is not a known git hook.
    """
    if name not in VALID_GIT_HOOKS:
        raise ValueError(
            f"'{name}' is not a recognized git hook name.\n"
            "  How to fix: Use a standard git hook name (e.g., post-checkout, pre-push)."
        )
    return name


def validate_safe_name(name: str) -> str:
    """Validate that a name is safe for use in filesystem paths.

    Returns the name unchanged if valid.
    Raises ValueError if the name contains path traversal or shell metacharacters.
    """
    if not name or not _SAFE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid name: {name!r} — contains path traversal or unsafe characters.\n"
            f"  Names must match: {_SAFE_NAME_RE.pattern}\n"
            f"  How to fix: Use only letters, numbers, hyphens, underscores, and dots."
        )
    return name


def is_valid_scope_name(name: str) -> bool:
    """Return True if *name* is a safe KB scope / directory slug.

    Same rule as validate_safe_name, but returns a bool instead of raising —
    for callers that render their own error message and exit code. Rejects "",
    path separators, leading '.'/'_'/'-', whitespace, and control characters.
    """
    return bool(name) and _SAFE_NAME_RE.match(name) is not None


# scp-like git remote: git@host:path
_SCP_LIKE_RE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:")


def validate_git_url(url: str) -> str | None:
    """Return an error string if *url* is not an allowed git transport, else None.

    Allowed: https://, http://, ssh://, scp-like ``git@host:path``, and local
    absolute paths. Everything else — ``git://`` (unauthenticated), transport
    helpers (``ext::``/``fd::``), option-like values, and control characters —
    is refused so a repository-controlled URL can neither run arbitrary commands
    nor inject git options.
    """
    if not url or not url.strip():
        return "URL is empty."
    if url != url.strip():
        return "URL has leading or trailing whitespace."
    if any(ord(c) < 0x20 for c in url):
        return "URL contains control characters."
    if url.startswith("-"):
        return "URL must not start with '-' (looks like a git option)."
    if "::" in url:
        return "URL uses a git transport helper (scheme::), which is not allowed."
    if url.startswith(("https://", "http://", "ssh://")):
        return None
    if url.startswith("/"):  # local absolute path (used by --local and tests)
        return None
    if _SCP_LIKE_RE.match(url):  # git@host:path
        return None
    if url.startswith("git://"):
        return "Unauthenticated git:// transport is not allowed."
    return (
        "Unsupported git transport "
        "(use https://, ssh://, git@host:path, or a local path)."
    )
