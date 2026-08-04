"""Review-lane policy gate: refuse a push that builds on an unapproved spec.

Kept separate from `pre_push.py`, which owns the hook protocol and kb-submodule
synchronization. This module knows only about policy: given a repo and the
branches being pushed, decide whether the review lane was respected.
"""

from __future__ import annotations

from pathlib import Path

from reinicorn.config import KB_DIR_NAME, kb_scope
from reinicorn.kb import branch_doc_path, get_kb_dir, kb_gitlink
from reinicorn.linter.spec_refs import (
    SPEC_DIR_NAME,
    declared_spec,
    doc_text_at,
    is_not_applicable,
    is_spec_path,
    resolve_ref,
    tracked_paths_at,
    unapproved_reason,
)
from reinicorn.mode import get_mode


def ensure_plan_spec_approved(root: Path, branches: list[str]) -> int:
    """Block the push when any pushed branch's plan builds on an unapproved spec.

    Everything here is read from the kb commit each pushed branch pins
    (``<branch>:kb``) — never from the kb index or worktree. What a reviewer
    checks out is that pinned commit, so a staged-but-uncommitted spec, an
    uncommitted status edit, or a kb commit the branch never pointed at must
    not satisfy the gate.

    Fails *open*, unlike `_ensure_kb_pushed`. That asymmetry is deliberate: the
    kb-pointer check guards data integrity, where a dangling pointer breaks every
    downstream checkout, so it must fail closed. This one guards a process norm,
    and a parse hiccup that silently bricks every push in the repo is worse than
    a missed policy warning.

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

        for branch in branches:
            if not branch:
                # A bare '' would make rev-parse read ':kb' — the index, the
                # exact desk state this gate must not consult.
                continue
            rev = kb_gitlink(root, branch)
            if rev is None:
                continue
            # A relative base yields the kb-relative path for tree lookup.
            plan_rel = branch_doc_path("plan", Path(scope), branch).as_posix()
            tracked = tracked_paths_at(kb_dir, rev)
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
            "branch pins",
            "Fix the path, or commit the doc to the kb and update the "
            "branch's kb pointer.",
        )

    if not is_spec_path(res.path):
        return _block(
            plan_path,
            f"'spec: {value}' resolves to '{res.path}', which is not a spec",
            f"Name a doc under '{SPEC_DIR_NAME}/', or 'N/A' if there is none.",
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
