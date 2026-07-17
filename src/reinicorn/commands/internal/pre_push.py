"""rcorn _pre-push — kb submodule sync."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reinicorn.config import KB_DIR_NAME
from reinicorn.git import repo_root, run_git
from reinicorn.kb import get_kb_dir
from reinicorn.mode import get_mode

if TYPE_CHECKING:
    from pathlib import Path


def cmd_pre_push() -> int:
    try:
        root = repo_root(quiet=True)
        if root is None:
            return 0
        return _ensure_kb_pushed(root)
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
        print(
            "\n\u274c Kb push failed. The parent push would create a dangling\n"
            "   submodule pointer that breaks CI and other checkouts.\n\n"
            f"   Fix: cd {KB_DIR_NAME} && git push origin main\n",
            flush=True,
        )
        return 1

    print("\U0001f984 Kb pushed successfully.")
    return 0
