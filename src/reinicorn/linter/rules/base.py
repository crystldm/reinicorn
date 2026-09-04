"""Abstract base class for lint rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Every built-in diagnostic reads ``<path>:<line> — <message>``: the
# project-relative path, a line, an em dash. The process gate keys on it to
# scope a rule's findings to one branch's docs.
DIAGNOSTIC_SEPARATOR = " — "


def diagnostic_path(diagnostic: str) -> str:
    """The project-relative path a ``path:line — message`` diagnostic names."""
    location = diagnostic.split(DIAGNOSTIC_SEPARATOR, 1)[0]
    return location.rsplit(":", 1)[0]


class LintRule(ABC):
    @abstractmethod
    def name(self) -> str:
        """Rule name (e.g. 'kb/cross-links')."""

    @abstractmethod
    def run(self, project_root: Path) -> list[str]:
        """Run the rule.  Return diagnostic messages (empty = pass)."""
