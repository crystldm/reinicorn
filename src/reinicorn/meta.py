"""Package self-knowledge: where this reinicorn install came from.

The Repository URL in pyproject [project.urls] is the single source of
truth for the reinicorn repo's home. Everything that must point back at the
repo (the CI workflow install source, the feedback issue target) derives
from it — moving or forking reinicorn means changing that one pyproject line.
"""

from __future__ import annotations

from reinicorn.git import gh_repo_from_url


def _load_metadata():
    from importlib.metadata import metadata

    return metadata("reinicorn")


def reinicorn_source_repo() -> str | None:
    """'owner/repo' from the installed package's Repository URL, else None."""
    for entry in _load_metadata().get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() == "repository":
            return gh_repo_from_url(url.strip())
    return None
