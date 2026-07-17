"""Abstract base class for lint rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class LintRule(ABC):
    @abstractmethod
    def name(self) -> str:
        """Rule name (e.g. 'kb/cross-links')."""

    @abstractmethod
    def run(self, project_root: Path) -> list[str]:
        """Run the rule.  Return diagnostic messages (empty = pass)."""
