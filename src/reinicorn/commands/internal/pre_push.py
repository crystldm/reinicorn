"""rcorn _pre-push — kb submodule sync and the review-lane gate."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from reinicorn.commands.internal.spec_gate import ensure_plan_spec_approved
from reinicorn.config import KB_DIR_NAME
from reinicorn.git import current_branch, explain_failure, repo_root, run_git
from reinicorn.kb import get_kb_dir
from reinicorn.mode import get_mode

if TYPE_CHECKING:
    from pathlib import Path

_NULL_OID = "0" * 40


def cmd_pre_push() -> int:
    # Read the hook's stdin before anything else: git feeds the refs being
    # pushed and the stream is consumed once.
    pushed = _pushed_branches()
    # None means no hook context at all (invoked by hand), where the checked-out
    # branch is the only sensible subject. An empty list means the hook did run
    # and carried no branch refs — a tag-only push, or deletions — and there is
    # no plan to check. Conflating the two would judge `git push origin v1.2.0`
    # against whatever plan happened to be checked out.
    branches = [current_branch()] if pushed is None else pushed
    try:
        root = repo_root(quiet=True)
        if root is None:
            return 0
        rc = _ensure_kb_pushed(root)
        if rc != 0:
            return rc
        return ensure_plan_spec_approved(root, branches)
    except Exception as e:
        # Fail closed: this guard exists to stop a parent push that would leave
        # a dangling kb submodule pointer. If the check itself errors we cannot
        # confirm the kb is pushed, so block the push rather than risk the
        # dangling ref. A genuine hook bug can still be bypassed per-push.
        print(
            f"\n❌ Kb pre-push check failed unexpectedly: {e}\n"
            "   Refusing the push to avoid a dangling kb submodule pointer.\n"
            f"   Inspect the kb (cd {KB_DIR_NAME} && git status), or bypass this\n"
            "   one push with: git push --no-verify\n",
            flush=True,
        )
        return 1


def _ensure_kb_pushed(root: Path) -> int:
    """Push kb submodule if it has unpushed commits referenced by parent.

    Runs synchronously BEFORE the parent push so CI can always fetch the submodule
    commit. Returns non-zero only if the kb needs pushing and the push fails.
    """
    kb_dir = get_kb_dir(root)
    if kb_dir is None:
        return 0

    mode = get_mode(root)
    if mode in ("incognito", "disabled"):
        return 0

    if not (kb_dir / ".git").exists():
        return 0

    r = run_git("rev-parse", f"HEAD:{KB_DIR_NAME}", check=False, cwd=root)
    if r.returncode != 0:
        return 0
    expected_sha = r.stdout.strip()
    if not expected_sha:
        return 0

    run_git("fetch", "origin", "main", "--quiet", cwd=kb_dir, check=False)

    r = run_git(
        "merge-base", "--is-ancestor", expected_sha, "origin/main",
        check=False, cwd=kb_dir,
    )
    if r.returncode == 0:
        return 0

    print("\U0001f984 Kb submodule has unpushed commits, pushing now...")
    r = run_git("push", "origin", "main", check=False, cwd=kb_dir)
    if r.returncode != 0:
        # A git hook writes straight to the user's terminal, so this prints
        # rather than going through console \u2014 but the text still comes from the
        # one seam, so "why" is never guessed at and git's own words survive.
        print("\n\u274c " + "\n".join(explain_failure("push the kb", r)))
        print(
            "\n   The parent push would create a dangling submodule pointer\n"
            "   that breaks CI and other checkouts.\n"
            "   Fix: rcorn kb publish (or bypass once with git push --no-verify)\n",
            flush=True,
        )
        return 1

    print("\U0001f984 Kb pushed successfully.")
    return 0


def _pushed_branches() -> list[str] | None:
    """Local branches being pushed, per the pre-push hook protocol.

    Git feeds one `<local ref> <local oid> <remote ref> <remote oid>` line per
    ref on stdin. Reading it matters: `git push origin other-branch` pushes a
    branch that is not checked out, so resolving the plan from HEAD would check
    the wrong branch and let the gate be bypassed in an ordinary workflow.

    Returns None when there is no hook context to read (no stdin, or a terminal),
    which is the caller's signal to fall back to the checked-out branch. An empty
    list is a different answer: the hook ran and named no branches, so nothing
    should be checked.
    """
    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        data = sys.stdin.read()
    except (OSError, ValueError):
        return None

    branches: list[str] = []
    for line in data.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        local_ref, local_oid = parts[0], parts[1]
        # Deletions carry a null oid and the literal "(delete)" local ref;
        # there is no plan to check for a branch being removed.
        if local_ref == "(delete)" or local_oid == _NULL_OID:
            continue
        if local_ref.startswith("refs/heads/"):
            branches.append(local_ref.removeprefix("refs/heads/"))
    return branches
