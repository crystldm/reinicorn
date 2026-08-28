"""Review-lane policy gate: refuse a push that builds on an unapproved spec.

Kept separate from `pre_push.py`, which owns the hook protocol and kb
publication. This module knows only about policy: given a repo and the
branches being pushed, decide whether the review lane was respected.
"""

from __future__ import annotations

from pathlib import Path

from reinicorn.config import KB_DIR_NAME, kb_scope
from reinicorn.git import explain_failure, run_git
from reinicorn.kb import branch_doc_path, get_kb_dir
from reinicorn.linter.spec_refs import (
    declared_spec,
    doc_text_at,
    is_not_applicable,
    is_spec_path,
    resolve_ref,
    spec_dir_name,
    tracked_paths_at,
    unapproved_reason,
)
from reinicorn.mode import get_mode


def ensure_plan_spec_approved(root: Path, branches: list[str]) -> int:
    """Block the push when any pushed branch's plan builds on an unapproved spec.

    Everything here is read from the kb clone's committed HEAD — always
    `main`, since `_ensure_kb_pushed` just published it — never from the kb
    index or worktree. What a reviewer checks out is that committed HEAD, so
    a staged-but-uncommitted spec or an uncommitted status edit must not
    satisfy the gate.

    Fails *open*, unlike `_ensure_kb_pushed`. That asymmetry is deliberate: the
    kb-push check guards data integrity — an unpublished kb commit leaves
    reviewers and CI unable to read the docs a push references — so it must
    fail closed. This one guards a process norm, and a parse hiccup that
    silently bricks every push in the repo is worse than a missed policy
    warning.

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

        if not branches:
            return 0

        # Name the whole push up front so a failure before the per-branch loop
        # still reports something useful.
        branch = ", ".join(branches)

        scope = kb_scope(root)

        head = run_git(
            "rev-parse", "--verify", "-q", "HEAD", check=False, cwd=kb_dir,
        )
        if head.returncode == 1:
            return 0  # unborn HEAD: an empty kb clone has nothing to gate on
        if head.returncode != 0:
            # Any other failure is a broken kb, not an empty one — route it
            # through the loud fail-open handler below.
            raise RuntimeError(
                "\n".join(explain_failure("resolve the kb clone's HEAD", head))
            )
        rev = head.stdout.strip()
        tracked = tracked_paths_at(kb_dir, rev)

        for branch in branches:
            if not branch:
                continue
            # A relative base yields the kb-relative path for tree lookup.
            plan_rel = branch_doc_path("plan", Path(scope), branch).as_posix()
            if plan_rel not in tracked:
                continue
            plan_path = f"{KB_DIR_NAME}/{plan_rel}"
            rc = _check_plan(
                doc_text_at(kb_dir, rev, plan_rel),
                plan_path, scope, kb_dir, rev, tracked,
            )
            if rc != 0:
                return rc

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


def _check_plan(
    text: str, plan_path: str, scope: str, kb_dir: Path, rev: str,
    tracked: frozenset[str],
) -> int:
    value = declared_spec(text)

    if value is None:
        return _block(
            plan_path,
            "its 'spec:' frontmatter field is missing or still the template placeholder",
            "Declare the spec this plan implements, or 'N/A' if it has none.",
        )
    if is_not_applicable(value):
        return 0

    res = resolve_ref(value, scope, tracked)
    if res.ambiguous:
        return _block(
            plan_path,
            f"'spec: {value}' is ambiguous — it matches "
            f"{', '.join(res.ambiguous)}",
            "Use a path that names exactly one doc.",
        )
    if res.path is None:
        return _block(
            plan_path,
            f"'spec: {value}' matches no path in the kb commit this "
            "push publishes",
            "Fix the path, or commit the doc to the kb before pushing.",
        )

    if not is_spec_path(res.path):
        return _block(
            plan_path,
            f"'spec: {value}' resolves to '{res.path}', which is not a spec",
            f"Name a doc under '{spec_dir_name()}/', or 'N/A' if there is none.",
        )

    reason = unapproved_reason(res.path, kb_dir, rev=rev)
    if reason:
        slug = res.path.rsplit("/", 1)[-1].removesuffix(".md")
        return _block(
            plan_path,
            f"its spec '{res.path}' is {reason}",
            f"Check the review: rcorn review status {slug}",
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
