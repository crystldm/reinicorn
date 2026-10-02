"""Internal: post-merge cleanup, invoked by the kb-repo CI workflow.

Usage: rcorn _review-cleanup <head-ref> [pr-url]
cwd MUST be the kb repo root (the Actions checkout of main).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from reinicorn import console
from reinicorn.review import cleanup_after_merge, make_target, parse_review_ref


def cmd_review_cleanup(args: list[str]) -> int:
    if not args:
        console.error("usage: rcorn _review-cleanup <head-ref> [pr-url]")
        return 1
    ref = parse_review_ref(args[0])
    if ref is None:
        # The workflow's if: only filters on the review/ prefix, so any merged
        # branch under it lands here — a non-lane ref is a skip, not a failure.
        console.info(f"not a review-lane ref: {args[0]} — skipping")
        return 0
    pr_url = args[1] if len(args) > 1 else ""
    kb_root = Path.cwd()
    target = make_target(ref.doc_type, ref.repo_scope, ref.slug, kb_root)
    try:
        changed = cleanup_after_merge(kb_root, target, pr_url=pr_url)
    except (RuntimeError, subprocess.CalledProcessError) as e:
        # CI entry point: surface a clean error + rc 1 instead of leaking a
        # raw traceback into the Actions log. RuntimeError is the documented
        # remote-facing contract; CalledProcessError covers the local-git one.
        console.error(f"review cleanup failed: {e}")
        return 1
    console.success("cleanup done" if changed else "already clean — no-op")
    return 0
