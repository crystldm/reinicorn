"""Review-lane policy gate: refuse a push that builds on an unapproved doc.

Kept separate from `pre_push.py`, which owns the hook protocol and kb
publication. This module knows only about policy: given a repo and the
branches being pushed, decide whether the review lane was respected — for
every branch-addressed doc type whose registry row declares a `depends_on`
relation (spec: process-as-config §2).
"""

from __future__ import annotations

from pathlib import Path

from reinicorn.config import KB_DIR_NAME, kb_scope
from reinicorn.corpus import doc_path
from reinicorn.doc_types import Addressing, DependsOn, registry
from reinicorn.git import explain_failure, run_git
from reinicorn.kb import get_kb_dir
from reinicorn.mode import get_mode
from reinicorn.refs import (
    declared_dependency,
    doc_text_at,
    is_not_applicable,
    path_in_dir,
    resolve_ref,
    tracked_paths_at,
    unapproved_reason,
)
from reinicorn.staging import STAGE_ACTIVE


def ensure_dependencies_approved(root: Path, branches: list[str]) -> int:
    """Block the push when any pushed branch's docs build on an unapproved doc.

    Everything here is read from the kb clone's committed HEAD — always
    `main`, since `_ensure_kb_pushed` just published it — never from the kb
    index or worktree. What a reviewer checks out is that committed HEAD, so
    a staged-but-uncommitted doc or an uncommitted status edit must not
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
    branch = checked_path = "<unknown>"
    try:
        kb_dir = get_kb_dir(root)
        if kb_dir is None or not (kb_dir / ".git").exists():
            return 0

        if get_mode(root) in ("incognito", "disabled"):
            return 0

        if not branches:
            return 0

        rows = registry(root)
        gated_rows = [
            dt for dt in rows.values()
            if dt.depends_on is not None
            and dt.addressing is Addressing.BRANCH
        ]
        if not gated_rows:
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
            for dt in gated_rows:
                rel = dt.depends_on
                if rel is None:
                    continue
                # A relative base yields the kb-relative path for tree lookup.
                stage = STAGE_ACTIVE if "{stage}" in dt.filename else None
                doc_rel = doc_path(
                    Path(scope), dt, branch, stage=stage,
                ).as_posix()
                if doc_rel not in tracked:
                    continue
                checked_path = f"{KB_DIR_NAME}/{doc_rel}"
                rc = _check_doc(
                    doc_text_at(kb_dir, rev, doc_rel), rel,
                    rows[rel.type].dir_path,
                    checked_path, scope, kb_dir, rev, tracked,
                )
                if rc != 0:
                    return rc

        return 0
    except Exception as e:
        print(
            "\n⚠️  Dependency-approval gate did not run"
            f" (branch {branch}, doc {checked_path}): {e}\n"
            "   Allowing the push — this gate fails open by design — but the\n"
            "   review lane was NOT checked for this push.\n",
            flush=True,
        )
        return 0


def _check_doc(
    text: str, rel: DependsOn, target_dir: str, checked_path: str,
    scope: str, kb_dir: Path, rev: str, tracked: frozenset[str],
) -> int:
    value = declared_dependency(text, rel)

    if value is None:
        return _block(
            checked_path, rel,
            f"its '{rel.field}:' frontmatter field is missing or still the "
            "template placeholder",
            f"Declare the {rel.type} this implements, or 'N/A' if it has none.",
        )
    if is_not_applicable(value):
        return 0

    res = resolve_ref(value, scope, tracked)
    if res.ambiguous:
        return _block(
            checked_path, rel,
            f"'{rel.field}: {value}' is ambiguous — it matches "
            f"{', '.join(res.ambiguous)}",
            "Use a path that names exactly one doc.",
        )
    if res.path is None:
        return _block(
            checked_path, rel,
            f"'{rel.field}: {value}' matches no path in the kb commit this "
            "push publishes",
            "Fix the path, or commit the doc to the kb before pushing.",
        )

    if not path_in_dir(res.path, target_dir):
        return _block(
            checked_path, rel,
            f"'{rel.field}: {value}' resolves to '{res.path}', which is not "
            f"a {rel.type}",
            f"Name a doc under '{target_dir}/', or 'N/A' if there is none.",
        )

    reason = unapproved_reason(res.path, kb_dir, rev=rev)
    if reason:
        slug = res.path.rsplit("/", 1)[-1].removesuffix(".md")
        return _block(
            checked_path, rel,
            f"its {rel.type} '{res.path}' is {reason}",
            f"Check the review: rcorn review status {slug}",
        )

    return 0


def _block(checked_path: str, rel: DependsOn, problem: str, remedy: str) -> int:
    print(
        f"\n❌ Push blocked: {checked_path} builds on an unapproved "
        f"{rel.type}.\n\n"
        f"   {problem}.\n\n"
        f"   {remedy}\n"
        "   Bypass this one push with: git push --no-verify\n",
        flush=True,
    )
    return 1
