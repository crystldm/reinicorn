"""Internal: candidate-integrity check, invoked by the kb-repo CI workflow
on every pull request (the "Candidate integrity" status check).

Usage: rcorn _review-check <head-ref>
cwd MUST be the kb repo root with the PR head checked out (the Actions
checkout of the PR), origin pointing at the kb remote.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from reinicorn import console
from reinicorn.review import (
    candidate_integrity_failures,
    make_target,
    parse_review_ref,
)


def cmd_review_check(args: list[str]) -> int:
    if not args:
        console.error("usage: rcorn _review-check <head-ref>")
        return 1
    ref = parse_review_ref(args[0])
    if ref is None:
        # The workflow runs on every PR; a non-lane branch has nothing to
        # verify — a skip, not a failure.
        console.info(f"not a review-lane ref: {args[0]} — skipping")
        return 0
    checkout = Path.cwd()
    target = make_target(ref.doc_type, ref.repo_scope, ref.slug, checkout)
    try:
        failures = candidate_integrity_failures(checkout, target)
    except (RuntimeError, subprocess.CalledProcessError) as e:
        # CI entry point: a clean error + rc 1, never a raw traceback in the
        # Actions log. RuntimeError is the documented remote-facing contract;
        # CalledProcessError covers the local-git one.
        console.error(f"candidate integrity check could not run: {e}")
        return 1
    if failures:
        for f in failures:
            console.error(f)
        return 1
    console.success(f"candidate '{target.final_rel}' matches its draft on kb main")
    return 0
