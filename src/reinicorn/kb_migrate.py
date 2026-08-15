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
from reinicorn.config import KB_DIR_NAME, config_set
from reinicorn.git import run_git
from reinicorn.kb_remote import (
    KB_REMOTE_KEY,
    configured_kb_remote_url,
    resolve_kb_remote_url,
)
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
    fetched = run_git("fetch", "origin", "main", check=False, cwd=kb_dir)
    if fetched.returncode != 0:
        # A stale cached origin/main must not vouch for publication when
        # the remote is unreachable — refusing beats deleting kb/ on
        # cached evidence.
        return (
            "its publication state cannot be verified "
            "(fetching origin/main failed)"
        )
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
        # Migration-only fallback: a parent cloned without submodule init
        # has no kb/.git to inherit from, and legacy repos predate
        # REINICORN_KB_REMOTE — the URL lives only in .gitmodules, the
        # very file this migration deletes. Normal clone remote
        # resolution deliberately does not read it.
        r = run_git(
            "config", "-f", ".gitmodules",
            "--get", f"submodule.{KB_DIR_NAME}.url",
            check=False, cwd=root,
        )
        if r.returncode == 0:
            url = r.stdout.strip()
    if not url:
        console.error(
            "Cannot migrate: no kb remote URL could be resolved.\n"
            f"  Where: {root / '.reinicorn-config'}\n"
            "  How to fix: set REINICORN_KB_REMOTE in .reinicorn-config, "
            "then rerun."
        )
        return False

    # The old kb clone being torn down below may be the *only* place this
    # URL is recorded (submodule-era repos predate REINICORN_KB_REMOTE) —
    # record it before anything destructive runs, so a failure partway
    # through teardown still leaves 'rcorn kb sync' able to recover. Only
    # when nothing is recorded yet: an explicitly configured REINICORN_KB_REMOTE
    # (a shared, team-chosen URL) must never be overwritten by the resolved
    # URL, which can be a personal override (e.g. an SSH rewrite) inherited
    # from the submodule clone being migrated away from.
    if not configured_kb_remote_url(root):
        config_set(KB_REMOTE_KEY, url, root)

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
    modules_backup = modules.with_name(f"{KB_DIR_NAME}.pre-clone-migration")
    if modules.exists():
        if modules_backup.exists():
            shutil.rmtree(modules_backup)
        shutil.move(str(modules), str(modules_backup))
    if kb_dir.exists():
        shutil.rmtree(kb_dir)

    try:
        setup_kb_clone(root, url)
    except KbSetupError as e:
        console.error(
            f"{e}\n"
            f"  The old kb git history is preserved at {modules_backup}.\n"
            f"  How to fix: run 'rcorn kb sync' — it will retry the clone "
            f"using the recorded {KB_REMOTE_KEY}."
        )
        console.next_step("rcorn kb sync")
        return False

    ensure_kb_gitignored(root)

    console.success("Kb migrated to a plain clone.")
    print()
    console.info("The gitlink removal is staged. Commit it yourself:")
    # .gitignore and .reinicorn-config are always touched by migration
    # (gitignore entry, recorded remote); .gitmodules only when it survived
    # stripping (other submodules) — its full deletion was already staged
    # by the strip helper.
    parts = [".gitignore", ".reinicorn-config"]
    if (root / ".gitmodules").is_file():
        parts.append(".gitmodules")
    console.info(f"  git add {' '.join(parts)}")
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
