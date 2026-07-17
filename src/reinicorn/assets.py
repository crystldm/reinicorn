"""Resolve bundled assets for both editable and wheel installs.

Wheel installs bundle assets under reinicorn/_data/ via hatchling
force-include. Editable/dev installs resolve from the repo root.
"""

from __future__ import annotations

from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent / "_data"


def get_asset_path(name: str) -> Path | None:
    """Return the path to a bundled asset, or None if not found.

    Checks the wheel-bundled _data/ directory first, then falls back
    to the repo root (for editable installs).
    """
    bundled = _DATA_DIR / name
    if bundled.exists():
        return bundled

    from reinicorn.git import reinicorn_root
    repo = reinicorn_root()
    candidate = repo / name
    if candidate.exists():
        return candidate

    return None
