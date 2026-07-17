"""Mode management: enabled / disabled / incognito."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reinicorn.git import repo_root
from reinicorn.identity import MODE_FILE_NAME, STATE_DIR_NAME

if TYPE_CHECKING:
    from pathlib import Path


def get_mode(root: Path | None = None) -> str:
    """Return current mode ('enabled', 'disabled', or 'incognito')."""
    if root is None:
        root = repo_root(quiet=True)
        if root is None:
            return "enabled"

    mode_file = root / STATE_DIR_NAME / MODE_FILE_NAME
    if mode_file.is_file():
        try:
            return mode_file.read_text().strip() or "enabled"
        except OSError:
            return "enabled"
    return "enabled"


def set_mode(mode: str, root: Path | None = None) -> None:
    """Write mode to the Reinicorn state directory."""
    if root is None:
        root = repo_root()
        if root is None:
            raise SystemExit(1)
    state_dir = root / STATE_DIR_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / MODE_FILE_NAME).write_text(mode + "\n")


def hook_check(root: Path | None = None) -> bool:
    """Return True if hooks should run (mode != disabled)."""
    return get_mode(root) != "disabled"


def can_publish(root: Path | None = None) -> bool:
    """Return True if publishing is allowed (mode == enabled)."""
    return get_mode(root) == "enabled"
