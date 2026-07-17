"""KB layout detection, require_kb_dir, and cross-branch overlap."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from reinicorn import console
from reinicorn.config import KB_DIR_NAME, kb_scope
from reinicorn.doc_types import REGISTRY
from reinicorn.git import file_transport_args, repo_root, run_git, sanitize_branch

if TYPE_CHECKING:
    import subprocess


def _parse_kb_submodule_path(text: str) -> str | None:
    """Extract the path= value from [submodule "kb"] in .gitmodules text.

    Returns None if no kb submodule entry is found.
    """
    in_kb_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == f'[submodule "{KB_DIR_NAME}"]':
            in_kb_section = True
            continue
        if in_kb_section:
            if stripped.startswith("["):
                break  # entered next section
            key, _, value = stripped.partition("=")
            if key.strip() == "path":
                return value.strip() or None
    return None


def get_kb_dir(root: Path | None = None) -> Path | None:
    """Return the kb submodule directory, or None if no submodule is configured."""
    if root is None:
        root = repo_root()
        if root is None:
            return None

    gitmodules = root / ".gitmodules"
    if not gitmodules.is_file():
        return None

    path_str = _parse_kb_submodule_path(gitmodules.read_text())
    if path_str is None:
        return None

    # .gitmodules is repository-controlled; refuse a path that resolves outside
    # the repo root (absolute paths, ../ traversal) before it is used for reads,
    # writes, or removals.
    candidate = root / path_str
    try:
        rel = candidate.resolve().relative_to(root.resolve())
    except ValueError:
        rel = None
    if rel is None or rel == Path():
        console.error(
            f"Refusing kb submodule path '{path_str}' from .gitmodules: "
            f"it does not resolve to a directory inside the repository root."
        )
        return None

    return candidate


def require_kb_dir(root: Path | None = None) -> Path:
    """Return the kb submodule path, or print an error and raise SystemExit(1)."""
    kb_dir = get_kb_dir(root)
    if kb_dir is None:
        console.error(
            "No kb submodule found. "
            "Run 'rcorn init' to set up the kb."
        )
        raise SystemExit(1)
    return kb_dir


def ensure_kb_on_main(kb_dir: Path) -> None:
    """Ensure the kb submodule is on the main branch.

    Handles both detached HEAD and accidental feature-branch checkouts.
    """
    r = run_git("symbolic-ref", "--short", "HEAD", check=False, cwd=kb_dir)
    if r.returncode != 0 or r.stdout.strip() != "main":
        run_git("checkout", "main", check=False, cwd=kb_dir)


def stage_kb_pointer(root: Path, kb_dir: Path) -> None:
    """Stage the kb submodule pointer in the parent repo index.

    Derives the relative path from root so it works even if .gitmodules
    uses a custom path (e.g. tools/kb instead of kb).
    """
    try:
        rel = kb_dir.relative_to(root)
    except ValueError:
        return
    run_git("add", str(rel), check=False, cwd=root)


def commit_kb(root: Path, message: str, *, kb_dir: Path | None = None) -> bool:
    """Auto-commit all changes inside the kb submodule.

    Returns True if a commit was made, False if nothing to commit
    or no kb submodule is configured.
    Pass kb_dir to skip the get_kb_dir() lookup when already resolved.
    """
    resolved = kb_dir if kb_dir is not None else get_kb_dir(root)
    if resolved is None or not resolved.is_dir():
        return False

    ensure_kb_on_main(resolved)

    run_git("add", "-A", cwd=resolved, check=False)

    r = run_git("diff", "--cached", "--quiet", check=False, cwd=resolved)
    if r.returncode == 0:
        return False  # Nothing staged

    r = run_git("commit", "-q", "-m", message, check=False, cwd=resolved)
    if r.returncode == 0:
        stage_kb_pointer(root, resolved)
        return True
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
    dt = REGISTRY[doc_type]
    return repo_dir / dt.dir_path / dt.filename.format(branch=sanitize_branch(branch))


def plan_dir(kb: Path, branch: str) -> Path:
    return branch_doc_path("plan", kb / kb_scope(), branch).parent


def active_plan_names(kb_dir: Path, slug: str) -> list[str]:
    """Return sorted active plan directory names for the given repo scope."""
    active = kb_dir / slug / REGISTRY["plan"].dir_path / "active"
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
    submodule, no other active branches, or the current branch has no
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
        active_dir = repo_dir / REGISTRY["plan"].dir_path / "active"
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
