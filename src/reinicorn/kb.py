"""KB layout detection, require_kb_dir, and cross-branch overlap."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reinicorn import console
from reinicorn.config import KB_DIR_NAME, kb_scope
from reinicorn.doc_types import registry
from reinicorn.git import (
    GitFailure,
    classify_result,
    explain_failure,
    file_transport_args,
    remote_url,
    repo_root,
    report_failure,
    run_git,
    sanitize_branch,
    url_protocol,
)

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Sequence
    from pathlib import Path


def get_kb_dir(root: Path | None = None) -> Path | None:
    """Return the kb clone directory, or None when no kb exists yet.

    The kb is an ordinary git clone at <root>/kb. A directory without a
    .git entry is not a kb — a leftover empty dir must not be treated as
    one. `.git` may be a file (transitional submodule checkout, linked
    worktree) or a directory (plain clone); both are real kbs.
    """
    if root is None:
        root = repo_root()
        if root is None:
            return None
    candidate = root / KB_DIR_NAME
    if (candidate / ".git").exists():
        return candidate
    return None


def require_kb_dir(root: Path | None = None) -> Path:
    """Return the kb directory, or print an error and raise SystemExit(1)."""
    kb_dir = get_kb_dir(root)
    if kb_dir is None:
        console.error(
            f"No kb found at {KB_DIR_NAME}/.\n"
            "  If this repo already uses Reinicorn (teammate clone): "
            "run 'rcorn kb sync' to clone it.\n"
            "  If Reinicorn was never set up here: run 'rcorn init'."
        )
        raise SystemExit(1)
    return kb_dir


def checkout_kb_main(kb_dir: Path) -> bool:
    """Fetch origin/main (best effort) and put kb HEAD on the main branch.

    The fetch comes first so "main" can mean origin/main rather than a
    possibly-stale local ref; offline is survivable (local commits publish
    later), so a failed fetch warns and continues. A failed checkout is
    reported and returns False — committing into a detached HEAD makes
    work look saved when it is not.
    """
    fta = file_transport_args(cwd=kb_dir)
    fetch = run_git(*fta, "fetch", "origin", "main", check=False, cwd=kb_dir)
    if fetch.returncode != 0:
        console.warn(
            "Could not fetch kb origin/main — continuing with the local ref."
        )

    r = run_git("symbolic-ref", "--short", "HEAD", check=False, cwd=kb_dir)
    if r.returncode != 0 or r.stdout.strip() != "main":
        co = run_git("checkout", "main", check=False, cwd=kb_dir)
        if co.returncode != 0:
            report_failure("put the kb on its main branch", co, warn=True)
            return False
    return True


def ensure_kb_on_main(kb_dir: Path) -> bool:
    """Put the kb on an up-to-date main. Returns False when it cannot.

    "Up to date" means: HEAD is main, and local main is not behind a
    fetched origin/main (fast-forwarded here; ahead-only is fine — those
    are unpublished doc commits). Never moves the working tree backwards
    and never discards uncommitted kb work.
    """
    if not checkout_kb_main(kb_dir):
        return False
    # Only meaningful when the fetch above succeeded; --ff-only on an
    # already-ahead main is a no-op ("Already up to date").
    has_remote_ref = run_git(
        "rev-parse", "--verify", "-q", "origin/main", check=False, cwd=kb_dir,
    )
    if has_remote_ref.returncode != 0:
        return True  # nothing fetched to compare against
    ff = run_git("merge", "--ff-only", "origin/main", check=False, cwd=kb_dir)
    if ff.returncode != 0:
        # A ff-only merge can fail on genuine divergence, but also on local
        # *uncommitted* edits that conflict with what origin/main advanced —
        # the ordinary publish-time state, since this runs before commit_kb
        # sweeps the working tree. Let git's own words distinguish the two
        # instead of guessing "diverged" for both.
        report_failure("fast-forward kb main to origin/main", ff)
        console.next_step("rcorn kb sync")
        return False
    return True


def commit_kb(
    root: Path,
    message: str,
    *,
    kb_dir: Path | None = None,
    paths: Sequence[Path] | None = None,
) -> bool:
    """Auto-commit changes inside the kb clone.

    By default sweeps up every change in the kb working tree (publish and
    review rely on this). Per-artifact create commands pass ``paths`` — the
    file(s) or dir(s) they touched — so an already-dirty tree cannot leak
    unrelated changes into their commit (issue #35).

    Returns True if a commit was made, False if nothing to commit
    or no kb clone is configured.
    Pass kb_dir to skip the get_kb_dir() lookup when already resolved.
    """
    resolved = kb_dir if kb_dir is not None else get_kb_dir(root)
    if resolved is None or not resolved.is_dir():
        return False

    if not ensure_kb_on_main(resolved):
        console.error(
            "Refusing to commit kb changes: the kb is not on an up-to-date "
            "main (see above).\n"
            f"  Where: {resolved}\n"
            "  Your edits are still in the kb working tree — nothing is lost.\n"
            "  How to fix: resolve the state above, then rerun this command."
        )
        return False

    # Pathspecs relative to the kb dir; `add -A -- <spec>` stages deletions
    # too, which plan-complete's directory move needs.
    specs = [str(p.relative_to(resolved)) for p in paths] if paths else []

    run_git("add", "-A", "--", *specs, cwd=resolved, check=False)

    r = run_git("diff", "--cached", "--quiet", "--", *specs, check=False, cwd=resolved)
    if r.returncode == 0:
        return False  # Nothing staged

    # The pathspec on commit keeps anything staged outside `specs` from
    # landing in this commit.
    r = run_git("commit", "-q", "-m", message, "--", *specs, check=False, cwd=resolved)
    if r.returncode == 0:
        return True
    # Distinct from the "nothing staged" return above: there WAS work and it
    # did not get saved. Returning False silently made that look identical to
    # a no-op, so a doc could appear written and never be committed.
    report_failure("commit the kb", r, warn=True)
    return False


def push_main_with_retry(kb_dir: Path) -> subprocess.CompletedProcess[str]:
    """Push kb main to origin; on rejection, pull --no-rebase and retry once.

    Returns the final push result — callers own success/failure messaging.
    """
    fta = file_transport_args(cwd=kb_dir)
    push = run_git(*fta, "push", "origin", "main", check=False, cwd=kb_dir)
    if push.returncode != 0:
        console.progress("Push failed, pulling latest and retrying...")
        run_git(*fta, "pull", "--no-rebase", "origin", "main", check=False, cwd=kb_dir)
        push = run_git(*fta, "push", "origin", "main", check=False, cwd=kb_dir)
    return push


def _push_detail(kind: str, url: str) -> list[str]:
    """Kb-vocabulary context lines for a push failure, on top of git's own."""
    lines = [f"remote: {url or '(none)'} ({url_protocol(url)})"]
    if kind == "non-fast-forward":
        lines.append("kb has conflicting changes. Resolve any conflicts in kb/, "
                     "then retry.")
    elif kind == "protected":
        lines.append("kb main is protected — the review lane owns this path.")
    return lines


def explain_push_failure(
    push: GitFailure, kb_dir: Path, *, action: str = "push kb main",
) -> list[str]:
    """Message lines for a failed kb push, without printing them.

    Splits from `report_push_failure` because the review lane raises its
    diagnosis rather than printing it.
    """
    kind = classify_result(push)
    return explain_failure(
        action, push, detail=_push_detail(kind, remote_url(kb_dir)),
    )


def push_next_steps(kind: str, kb_dir: Path) -> list[str]:
    """The commands that actually move a stuck kb push forward.

    Never suggests the command that just failed unless retrying is genuinely
    the fix: an auth failure retried is an infinite loop, which is exactly how
    the original misdiagnosis wasted a session.
    """
    if kind == "non-fast-forward":
        return ["rcorn kb publish"]
    if kind == "protected":
        return ["rcorn review start <draft>"]
    if kind == "auth":
        from reinicorn.kb_remote import adapt_url_to_git_protocol

        url = remote_url(kb_dir)
        suggested = adapt_url_to_git_protocol(url) if url else ""
        if suggested and suggested != url:
            return [f"rcorn kb git remote set-url origin {suggested}"]
        return ["gh auth status"]
    return ["rcorn kb git status"]


def report_push_failure(
    push: GitFailure, kb_dir: Path, *,
    action: str = "push kb main", warn: bool = False,
) -> str:
    """Print why the kb push failed and what to run next. Returns the kind.

    Every lane that pushes the kb goes through here, so the diagnosis and the
    next step cannot drift between them. *warn* is for flows where the push is
    the last, non-fatal step and the command still succeeds — the text is
    identical, only the channel changes; *action* names the specific push when
    it is not kb main.
    """
    kind = classify_result(push)
    report_failure(
        action, push, detail=_push_detail(kind, remote_url(kb_dir)), warn=warn,
    )
    console.next_step(*push_next_steps(kind, kb_dir))
    return kind


def branch_changed_files(branch: str, root: Path | None = None) -> set[str]:
    """Return files changed by `branch` vs the merge-base with main.

    Tries `origin/main`, then local `main`/`master`. Returns an empty set if
    no main-like base can be resolved — overlap detection is informational,
    so a fabricated base would be worse than no signal.
    """
    if root is None:
        root = repo_root(quiet=True)
        if root is None:
            return set()

    r = run_git("rev-parse", "--verify", branch, check=False, cwd=root)
    if r.returncode != 0:
        return set()

    merge_base = ""
    for base in ("origin/main", "main", "master"):
        r = run_git("rev-parse", "--verify", base, check=False, cwd=root)
        if r.returncode != 0:
            continue
        rb = run_git("merge-base", base, branch, check=False, cwd=root)
        if rb.returncode == 0 and rb.stdout.strip():
            merge_base = rb.stdout.strip()
            break

    if not merge_base:
        return set()

    r = run_git("diff", "--name-only", f"{merge_base}..{branch}", check=False, cwd=root)
    if r.returncode != 0:
        return set()
    return {line for line in r.stdout.splitlines() if line}


def branch_dir_name(branch: str) -> str:
    """Directory name a branch's exec-plan docs live under."""
    return sanitize_branch(branch)


def branch_doc_path(doc_type: str, repo_dir: Path, branch: str) -> Path:
    """Full path of a branch-addressed doc (plan/retro) inside a repo scope dir."""
    dt = registry()[doc_type]
    return repo_dir / dt.dir_path / dt.filename.format(branch=sanitize_branch(branch))


def plan_dir(kb: Path, branch: str) -> Path:
    return branch_doc_path("plan", kb / kb_scope(), branch).parent


def active_plan_names(kb_dir: Path, slug: str) -> list[str]:
    """Return sorted active plan directory names for the given repo scope."""
    active = kb_dir / slug / registry()["plan"].dir_path / "active"
    if not active.is_dir():
        return []
    return sorted(d.name for d in active.iterdir() if d.is_dir())


def overlap_line(branch: str, root: Path) -> str:
    """Return the single-line overlap summary for compact dashboards.

    None (no basis for comparison) and [] (compared, none found) both
    collapse to "none" here — the dashboards only distinguish "nothing to
    worry about" from "go check kb status".
    """
    overlaps = overlapping_branches(branch, root)
    if overlaps:
        return f"overlap: {len(overlaps)} branch(es) — see rcorn kb status"
    return "overlap: none"


def repo_kb_dir(kb_dir: Path) -> Path:
    """Return the repo-scoped subdirectory inside the kb.

    Creates it if it doesn't exist. Path: kb/{scope}/
    """
    slug = kb_scope()
    repo_dir = kb_dir / slug
    repo_dir.mkdir(parents=True, exist_ok=True)
    return repo_dir


def overlapping_branches(
    current_branch: str, root: Path | None = None
) -> list[tuple[str, set[str]]] | None:
    """Return (branch, overlapping_files) for each other active branch that
    shares changed files with `current_branch`.

    Queries git directly (no kb files read). Active branches are discovered
    by directory name under ``kb/*/exec-plans/active/``. Results are sorted
    by branch name; only branches with a non-empty overlap are included.

    Returns None when there is no basis for comparison (no repo root, no kb
    clone, no other active branches, or the current branch has no
    changed files vs main) — distinct from an empty list, which means the
    comparison actually ran and found no overlap.
    """
    if root is None:
        root = repo_root(quiet=True)
        if root is None:
            return None

    resolved = get_kb_dir(root)
    if resolved is None:
        return None

    other_branches: set[str] = set()
    sanitized_current = sanitize_branch(current_branch)
    for repo_dir in sorted(resolved.iterdir()):
        if not repo_dir.is_dir() or repo_dir.name.startswith((".", "_")):
            continue
        active_dir = repo_dir / registry()["plan"].dir_path / "active"
        if not active_dir.is_dir():
            continue
        for entry in sorted(active_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue
            if entry.name == sanitized_current:
                continue
            other_branches.add(entry.name)

    if not other_branches:
        return None

    our_files = branch_changed_files(current_branch, root)
    if not our_files:
        return None

    results: list[tuple[str, set[str]]] = []
    for other in sorted(other_branches):
        other_files = branch_changed_files(other, root)
        if not other_files:
            continue
        overlap = our_files & other_files
        if not overlap:
            continue
        results.append((other, overlap))

    return results


def check_overlap(current_branch: str, root: Path | None = None) -> bool:
    """Warn if any other active branch has changed files that also changed here.

    Prints a multi-line block via `overlapping_branches`. Silent when there
    is no basis for comparison (see `overlapping_branches`). Returns True if
    any overlap is found.
    """
    overlaps = overlapping_branches(current_branch, root)

    if overlaps is None:
        return False

    if not overlaps:
        console.success("No overlap with other active branches.")
        print()
        return False

    console.header("Cross-branch overlap detected")
    print()
    for other, overlap in overlaps:
        console.warn(f"Branch '{other}' overlaps on {len(overlap)} file(s):")
        for f in sorted(overlap)[:5]:
            console.info(f"  {f}")
        if len(overlap) > 5:
            console.info(f"  ... and {len(overlap) - 5} more")
        print()

    return True
