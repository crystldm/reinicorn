"""Migrate a repo from the kb-submodule layout to the plain-clone layout.

Detection inspects the index for a mode-160000 kb entry, not just
`.gitmodules` — an orphan gitlink with no `.gitmodules` section (or a
malformed `.gitmodules`) migrates too. The unpublished-work check runs
before anything destructive: every later step assumes the old kb
worktree is disposable, and losing a draft to a migration would be
unforgivable.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from reinicorn import console
from reinicorn.config import KB_DIR_NAME
from reinicorn.git import run_git
from reinicorn.kb_remote import resolve_kb_remote_url
from reinicorn.kb_setup import KbSetupError, ensure_kb_gitignored, setup_kb_clone

_GITLINK_MODE = "160000"


def detect_submodule_layout(root: Path) -> bool:
    """True when the index tracks a kb gitlink or .gitmodules declares one."""
    r = run_git("ls-files", "-s", "--", KB_DIR_NAME, check=False, cwd=root)
    for line in r.stdout.splitlines():
        mode, _, rest = line.partition(" ")
        path = rest.split("\t", 1)[-1] if "\t" in rest else ""
        if mode == _GITLINK_MODE and path == KB_DIR_NAME:
            return True
    gitmodules = root / ".gitmodules"
    return (
        gitmodules.is_file()
        and f'[submodule "{KB_DIR_NAME}"]' in gitmodules.read_text()
    )


def kb_unpublished_reason(kb_dir: Path) -> str | None:
    """Why the old kb worktree cannot be discarded, or None when it can."""
    if not (kb_dir / ".git").exists():
        return None  # nothing checked out — nothing to lose
    dirty = run_git("status", "--porcelain", check=False, cwd=kb_dir)
    if dirty.stdout.strip():
        return "it has uncommitted changes"
    run_git("fetch", "origin", "main", check=False, cwd=kb_dir)
    ahead = run_git(
        "rev-list", "--count", "origin/main..HEAD", check=False, cwd=kb_dir,
    )
    if ahead.returncode != 0:
        return "its commits cannot be verified against origin/main (fetch failed?)"
    if ahead.stdout.strip() != "0":
        return "it has commits that are not on origin/main"
    return None


def migrate_submodule_to_clone(root: Path) -> bool:
    """Convert the kb submodule at KB_DIR_NAME into a gitignored plain clone.

    Step order mirrors spec §10: the refuse-if-unpublished check runs
    before any destructive command. Leaves the gitlink removal staged and
    prints exactly what to commit — never commits on the user's behalf.
    """
    kb_dir = root / KB_DIR_NAME

    reason = kb_unpublished_reason(kb_dir)
    if reason is not None:
        console.error(
            f"Refusing to migrate the kb submodule: {reason}.\n"
            f"  Where: {kb_dir}\n"
            "  How to fix: publish it first (rcorn kb publish), then rerun "
            "this command."
        )
        return False

    # Resolve the clone URL before dismantling anything that records it.
    url = resolve_kb_remote_url(root)
    if not url:
        console.error(
            "Cannot migrate: no kb remote URL could be resolved.\n"
            "  How to fix: set REINICORN_KB_REMOTE in .reinicorn-config, "
            "then rerun."
        )
        return False

    console.progress("Migrating kb from submodule to plain clone...")

    registered = run_git(
        "config", "--get", f"submodule.{KB_DIR_NAME}.url",
        check=False, cwd=root,
    ).returncode == 0
    if registered:
        run_git("submodule", "deinit", "-f", KB_DIR_NAME, check=False, cwd=root)
    run_git("rm", "-q", "--cached", "-f", KB_DIR_NAME, check=False, cwd=root)

    _strip_gitmodules_section(root)
    run_git(
        "config", "--remove-section", f"submodule.{KB_DIR_NAME}",
        check=False, cwd=root,
    )

    modules = _git_common_dir(root) / "modules" / KB_DIR_NAME
    if modules.exists():
        backup = modules.with_name(f"{KB_DIR_NAME}.pre-clone-migration")
        if backup.exists():
            shutil.rmtree(backup)
        shutil.move(str(modules), str(backup))
    if kb_dir.exists():
        shutil.rmtree(kb_dir)

    try:
        setup_kb_clone(root, url)
    except KbSetupError as e:
        console.error(str(e))
        console.next_step("rcorn kb sync")
        return False

    ensure_kb_gitignored(root)

    console.success("Kb migrated to a plain clone.")
    print()
    console.info("The gitlink removal is staged. Commit it yourself:")
    # .gitmodules edits need staging only when the file survived (other
    # submodules); its full deletion was already staged by the strip helper.
    extra = " .gitmodules" if (root / ".gitmodules").is_file() else ""
    console.info(f"  git add .gitignore{extra}")
    console.info("  git commit -m 'chore: migrate kb from submodule to clone'")
    return True


def _strip_gitmodules_section(root: Path) -> None:
    """Remove the kb section from .gitmodules; delete the file when empty."""
    gitmodules = root / ".gitmodules"
    if not gitmodules.is_file():
        return
    kept: list[str] = []
    in_kb = False
    for line in gitmodules.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_kb = stripped == f'[submodule "{KB_DIR_NAME}"]'
        if not in_kb:
            kept.append(line)
    if any(line.strip() for line in kept):
        gitmodules.write_text("\n".join(kept) + "\n")
    else:
        gitmodules.unlink()
        run_git("rm", "-q", "--cached", "--ignore-unmatch", ".gitmodules",
                check=False, cwd=root)


def _git_common_dir(root: Path) -> Path:
    r = run_git("rev-parse", "--git-common-dir", check=False, cwd=root)
    common = Path(r.stdout.strip() or ".git")
    return common if common.is_absolute() else root / common
