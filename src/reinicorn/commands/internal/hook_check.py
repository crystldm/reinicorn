"""rcorn _hook-check — exit 0 if hooks should run, 1 if disabled."""

from __future__ import annotations

from reinicorn.mode import hook_check


def cmd_hook_check() -> int:
    return 0 if hook_check() else 1
