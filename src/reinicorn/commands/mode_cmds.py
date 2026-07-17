"""Mode management commands: enable, disable, incognito, status."""

from __future__ import annotations

from reinicorn import console
from reinicorn.mode import get_mode, set_mode


def cmd_enable() -> int:
    if get_mode() == "enabled":
        console.info("Reinicorn already enabled (no-op).")
        return 0
    set_mode("enabled")
    console.success("Reinicorn enabled. Hooks and publishing are active.")
    return 0


def cmd_disable() -> int:
    if get_mode() == "disabled":
        console.info("Reinicorn already disabled (no-op).")
        console.next_step("rcorn mode enable")
        return 0
    set_mode("disabled")
    console.success("Reinicorn disabled. All hooks are no-ops, publishing is blocked.")
    console.next_step("rcorn mode enable")
    return 0


def cmd_incognito() -> int:
    if get_mode() == "incognito":
        console.info("Already in incognito mode (no-op).")
        console.next_step("rcorn mode enable")
        return 0
    set_mode("incognito")
    console.success("Incognito mode on. Syncing works, publishing is blocked.")
    console.next_step("rcorn mode enable")
    return 0


def cmd_mode_status() -> int:
    current = get_mode()
    console.info(f"Reinicorn mode: {current}")
    return 0
