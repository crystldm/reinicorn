"""Colored terminal output with NO_COLOR / FORCE_COLOR / isatty support.

Axi channel model: stdout carries all agent-consumed output (data, structured
errors, and next-step suggestions); stderr carries only progress/debug
diagnostics; exit codes carry status. Never put data an agent needs on
stderr, and never put progress noise on stdout.
"""

from __future__ import annotations

import os
import sys


def _is_tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return _is_tty()


_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _c(code: str, text: str) -> str:
    if _use_color():
        return f"{code}{text}{_RESET}"
    return text


def _pad() -> str:
    return "  " if _is_tty() else ""


def info(msg: str) -> None:
    print(f"{_pad()}{msg}")


def success(msg: str) -> None:
    print(f"{_pad()}{_c(_GREEN, msg)}")


def warn(msg: str) -> None:
    print(f"{_pad()}{_c(_YELLOW, msg)}")


def error(msg: str) -> None:
    """Structured error on stdout (agents read stdout; exit codes carry status)."""
    print(_c(_RED, f"error: {msg}"))


def progress(msg: str) -> None:
    """Progress/debug diagnostic on stderr — never data."""
    print(msg, file=sys.stderr)


def next_step(*commands: str) -> None:
    """Axi contextual disclosure: one `next: <command>` line per suggestion."""
    for cmd in commands:
        print(f"next: {cmd}")


def header(msg: str) -> None:
    print(_c(_BOLD, msg))
