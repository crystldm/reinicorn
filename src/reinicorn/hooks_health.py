"""Classify installed git hook scripts: stale reins-era hooks and marker reachability.

Shared by `rcorn hooks install` (repair decisions) and `rcorn kb status`
(surfacing dead guards) so both agree on what "healthy" means (issue #24).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

MARKER = "# --- reinicorn hooks below ---"
OLD_MARKER = "# --- reins hooks below ---"
HOOK_NAMES = ("post-checkout", "post-merge", "pre-push")

# Delegation to the pre-rename binary: `command -v reins` guards or a direct
# `reins _pre-push`-style call. Tight enough not to match prose or "reinicorn".
_REINS_DELEGATION = re.compile(r"\bcommand -v reins\b|\breins\s+_[a-z-]+")

# An `exit`, `exit 0`, `exit $?`, ... statement — execution never continues
# past it. Matched against the last `;`-separated statement of top-level
# (unindented) lines only: indented exits are conditional by construction,
# which is the cheap approximation the repair logic needs (no shell parsing).
_UNCONDITIONAL_EXIT = re.compile(r"^exit(\s+(\d+|\$\?))?\s*$")


def _line_forces_exit(line: str) -> bool:
    """True when this line always terminates the script: a top-level
    unconditional exit, plain (`exit 0`) or compound (`lint; exit $?`).

    The `;` split is naive — a quoted `;` can misparse — but a quoted string
    ending in `exit 0"` doesn't match the exit pattern, so it errs safe.
    """
    if line != line.lstrip() or line.startswith("#"):
        return False
    return bool(_UNCONDITIONAL_EXIT.match(line.split(";")[-1].strip()))


def is_stale_reins_hook(text: str) -> bool:
    """True for a hook written by the pre-rename `reins` tooling.

    Such hooks silently no-op (the `reins` binary is gone) and are Reinicorn's
    own output, so install may replace them wholesale rather than append.
    """
    return OLD_MARKER in text or bool(_REINS_DELEGATION.search(text))


def can_fall_through(text: str) -> bool:
    """True when execution can reach content appended to this script.

    False when the last effective (non-blank, non-comment) statement is a
    top-level unconditional `exit` — anything appended after it is dead code.
    """
    last = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        last = line
    if last is None:
        return True
    return not _line_forces_exit(last)


def marker_reachable(text: str) -> bool:
    """True when the reinicorn marker is present and execution can reach it
    (no top-level unconditional `exit` precedes it)."""
    if MARKER not in text:
        return False
    before = text.split(MARKER, 1)[0]
    return all(not _line_forces_exit(line) for line in before.splitlines())


@dataclass(frozen=True)
class HookIssue:
    name: str
    problem: str


def hook_issues(hooks_dir: Path) -> list[HookIssue]:
    """Dead-guard report for `kb status`: stale reins-era hooks and hooks
    whose reinicorn marker sits after an unconditional exit."""
    issues: list[HookIssue] = []
    for name in HOOK_NAMES:
        f = hooks_dir / name
        if not f.is_file():
            continue
        try:
            text = f.read_text()
        except OSError:
            continue
        if is_stale_reins_hook(text):
            issues.append(
                HookIssue(name, "stale reins-era hook — the kb guard never runs")
            )
        elif MARKER in text and not marker_reachable(text):
            issues.append(
                HookIssue(
                    name,
                    "reinicorn marker is unreachable — the kb guard never runs",
                )
            )
    return issues
