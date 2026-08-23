"""Thin wrapper around the gh CLI.

Centralizes auth checking, repo creation, and error handling.
Other commands (feedback, etc.) can migrate to this module later.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from reinicorn import console


def gh_available() -> bool:
    """Check if gh CLI is installed."""
    return shutil.which("gh") is not None


def run_gh(
    *args: str,
    check: bool = True,
    interactive: bool = False,
    input_text: str | None = None,
    error_hint: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a gh CLI command.

    Args:
        args: Arguments to pass to gh.
        check: If True, raise RuntimeError on non-zero exit.
        interactive: If True, inherit stdin/stdout for interactive commands.
        input_text: If set, piped to the process's stdin (e.g. for
            'gh api --input -').
        error_hint: Overrides the default "How to fix" line in the
            check-failure error (default suggests checking 'gh auth status').

    Returns:
        CompletedProcess with stdout/stderr captured (empty when interactive).
    """
    kwargs: dict = {"check": False}
    if interactive:
        kwargs["text"] = True
    else:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    if input_text is not None:
        kwargs["input"] = input_text
        kwargs["text"] = True
    try:
        r = subprocess.run(["gh", *args], **kwargs)
    except FileNotFoundError:
        raise RuntimeError(
            "gh CLI not found.\n"
            "  How to fix: Install gh from https://cli.github.com/"
        ) from None
    if check and r.returncode != 0:
        stderr = getattr(r, "stderr", "") or ""
        hint = error_hint or "Check 'gh auth status' and retry."
        raise RuntimeError(
            f"gh failed: gh {' '.join(args)}\n"
            f"  Exit code: {r.returncode}\n"
            f"  Error: {stderr.strip()}\n"
            f"  How to fix: {hint}"
        )
    return r


def gh_authenticated() -> bool:
    """Check if gh is authenticated with GitHub."""
    r = run_gh("auth", "status", check=False)
    return r.returncode == 0


def gh_auth_login() -> bool:
    """Run gh auth login interactively. Returns True on success."""
    console.info("Starting GitHub authentication...")
    r = run_gh("auth", "login", check=False, interactive=True)
    return r.returncode == 0


def gh_repo_create(
    name: str,
    *,
    private: bool = True,
    description: str = "",
) -> str:
    """Create a GitHub repo and return its clone URL.

    Args:
        name: Repo name (e.g. 'my-project-kb').
        private: Create as private repo (default True).
        description: Optional repo description.

    Returns:
        The clone URL of the created repo.
    """
    args = ["repo", "create", name, "--confirm"]
    if private:
        args.append("--private")
    if description:
        args.extend(["--description", description])
    r = run_gh(*args)
    return r.stdout.strip()


# GitHub API enum values (external contract, mirrored once here)
PR_STATE_OPEN = "OPEN"
REVIEW_DECISION_APPROVED = "APPROVED"


def gh_pr_create(
    repo: str, *, head: str, title: str, body: str,
    reviewers: list[str] | None = None,
) -> str:
    """Open a PR from *head* into the repo's default branch. Returns the URL."""
    args = [
        "pr", "create", "--repo", repo, "--head", head,
        "--title", title, "--body", body,
    ]
    for r in reviewers or []:
        args.extend(["--reviewer", r])
    return run_gh(
        *args,
        error_hint=(
            "A PR for this branch may already exist — "
            "check 'gh pr list' for the repo."
        ),
    ).stdout.strip()


def gh_pr_view(repo: str, *, head: str) -> dict | None:
    """PR metadata for the PR whose head branch is *head*, or None.

    Note: 'reviewDecision' may be None (repos without required reviews,
    or no reviews yet).
    """
    r = run_gh(
        "pr", "view", head, "--repo", repo,
        "--json", "number,state,reviewDecision,url,latestReviews",
        check=False,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return json.loads(r.stdout)


def gh_pr_merge(repo: str, number: int) -> None:
    """Squash-merge a PR."""
    run_gh(
        "pr", "merge", str(number), "--repo", repo, "--squash",
        error_hint=(
            "The PR may be unmergeable (approvals dismissed, required status "
            "checks red or pending, branch "
            "protection, or conflicts) — check the PR page."
        ),
    )


def gh_repo_is_solo(repo: str) -> bool | None:
    """True if *repo* has at most one push-capable collaborator.

    Returns False when two or more collaborators can push, and None when it
    can't be determined (listing failed, or the token can't inspect
    collaborators) — callers must never treat unknown as solo.

    A solo repo can never satisfy a required-review gate: GitHub forbids
    approving your own PR, so the lone maintainer (always the PR author) is the
    only possible reviewer. Callers use this to offer a self-review path
    instead of a structurally-unsatisfiable dead-end.
    """
    r = run_gh(
        "api", f"repos/{repo}/collaborators?per_page=100", "--paginate",
        check=False,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        collaborators = json.loads(r.stdout)
    except ValueError:
        return None
    if not isinstance(collaborators, list):
        return None
    # Count push-capable collaborators (write/maintain/admin all set push=True).
    # permissions may be absent for some token scopes — treat missing as unknown
    # rather than counting it, but if we can't see anyone's push bit at all we
    # still fall through to a definite count of what we could read.
    push_capable = sum(
        1 for c in collaborators
        if isinstance(c, dict) and (c.get("permissions") or {}).get("push")
    )
    return push_capable <= 1


def gh_login() -> str | None:
    """The authenticated GitHub login, or None if it can't be resolved."""
    r = run_gh("api", "user", "--jq", ".login", check=False)
    login = r.stdout.strip()
    return login if r.returncode == 0 and login else None


def gh_pr_close(repo: str, number: int, comment: str = "") -> None:
    """Close a PR, optionally with a comment."""
    args = ["pr", "close", str(number), "--repo", repo]
    if comment:
        args.extend(["--comment", comment])
    run_gh(
        *args,
        error_hint="The PR may already be closed or merged — check the PR page.",
    )
