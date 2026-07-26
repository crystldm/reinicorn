"""rcorn _pre-push — kb submodule sync."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reinicorn.config import KB_DIR_NAME, kb_scope
from reinicorn.git import current_branch, explain_failure, repo_root, run_git
from reinicorn.kb import branch_doc_path, get_kb_dir
from reinicorn.linter.spec_refs import (
    declared_spec,
    is_not_applicable,
    resolve_ref,
    tracked_paths,
    unapproved_reason,
)
from reinicorn.mode import get_mode

if TYPE_CHECKING:
    from pathlib import Path


def cmd_pre_push() -> int:
    try:
        root = repo_root(quiet=True)
        if root is None:
            return 0
        rc = _ensure_kb_pushed(root)
        if rc != 0:
            return rc
        return _ensure_plan_spec_approved(root)
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


def _ensure_plan_spec_approved(root: Path) -> int:
    """Block the push when this branch's plan builds on an unapproved spec.

    Fails *open*, unlike `_ensure_kb_pushed` above. That asymmetry is deliberate:
    the kb-pointer check guards data integrity, where a dangling pointer breaks
    every downstream checkout, so it must fail closed. This one guards a process
    norm, and a parse hiccup that silently bricks every push in the repo is worse
    than a missed policy warning.

    Fail-open is loud, though. A gate that degrades silently is indistinguishable
    from one that was never wired up, which is exactly how the `reins`-era hooks
    went unnoticed for weeks — so the exception path names what did not run.
    """
    branch = plan_path = "<unknown>"
    try:
        kb_dir = get_kb_dir(root)
        if kb_dir is None or not (kb_dir / ".git").exists():
            return 0

        if get_mode(root) in ("incognito", "disabled"):
            return 0

        branch = current_branch(cwd=root)
        if not branch:
            return 0

        scope = kb_scope(root)
        plan = branch_doc_path("plan", kb_dir / scope, branch)
        if not plan.is_file():
            return 0
        plan_path = str(plan.relative_to(root))

        value = declared_spec(plan.read_text())

        if value is None:
            return _block(
                plan_path,
                "its '**Spec:**' field is missing or still the template placeholder",
                "Declare the spec this plan implements, or 'N/A' if it has none.",
            )
        if is_not_applicable(value):
            return 0

        res = resolve_ref(value, scope, tracked_paths(kb_dir))
        if res.ambiguous:
            return _block(
                plan_path,
                f"'**Spec:** {value}' is ambiguous — it matches "
                f"{', '.join(res.ambiguous)}",
                "Use a path that names exactly one doc.",
            )
        if res.path is None:
            return _block(
                plan_path,
                f"'**Spec:** {value}' matches no git-tracked kb path",
                "Fix the path, or commit and publish the doc it names.",
            )

        reason = unapproved_reason(res.path, kb_dir)
        if reason:
            slug = res.path.rsplit("/", 1)[-1].removesuffix(".md")
            return _block(
                plan_path,
                f"its spec '{res.path}' is {reason}",
                f"Check the review: rcorn review status {slug}",
            )

        return 0
    except Exception as e:
        print(
            "\n⚠️  Spec-approval gate did not run"
            f" (branch {branch}, plan {plan_path}): {e}\n"
            "   Allowing the push — this gate fails open by design — but the\n"
            "   review lane was NOT checked for this push.\n",
            flush=True,
        )
        return 0


def _block(plan_path: str, problem: str, remedy: str) -> int:
    print(
        f"\n❌ Push blocked: {plan_path} builds on an unapproved spec.\n\n"
        f"   {problem}.\n\n"
        f"   {remedy}\n"
        "   Bypass this one push with: git push --no-verify\n",
        flush=True,
    )
    return 1
