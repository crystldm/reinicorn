"""Commit-pinned upstream source fetch: cached tarball download and extraction."""

from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from reinicorn.manifest import sha256_file
from reinicorn.skillset.adapter import AdapterError

if TYPE_CHECKING:
    from reinicorn.skillset.adapter import AdapterSource

# A stalled connection has no default timeout (`urlopen(url)` blocks
# indefinitely) — bound every download so a dead upstream can't hang a fetch.
_DOWNLOAD_TIMEOUT_SECONDS = 60


def tarball_url(source: AdapterSource) -> str:
    """The codeload.github.com tarball URL for a commit-pinned source."""
    return f"https://codeload.github.com/{source.repo}/tar.gz/{source.commit}"


def default_cache_dir() -> Path:
    """`$REINICORN_CACHE_DIR`, or `~/.cache/reinicorn/skillsets` if unset."""
    override = os.environ.get("REINICORN_CACHE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "reinicorn" / "skillsets"


def fetch_source(
    source: AdapterSource,
    cache_dir: Path,
    *,
    expected_digest: str | None = None,
) -> tuple[Path, str]:
    """Fetch, cache, verify, and extract the pinned upstream tarball.

    Returns `(extracted tree root, archive sha256)`. Downloads via urllib and
    caches under `cache_dir` keyed by repo and commit; a cached archive is
    reused without re-downloading. If `expected_digest` is given (from the
    lockfile) and the archive digest differs, raises `AdapterError` naming
    both. Extraction always uses tarfile's "data" filter, so archives with
    unsafe members (e.g. ones that would extract outside the destination
    directory) are rejected.

    The caller owns eventual cleanup of the returned tree's parent temp directory.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    owner, name = source.repo.split("/", 1)
    cache_path = cache_dir / f"{owner}__{name}__{source.commit}.tar.gz"

    if not cache_path.is_file():
        _download(source, cache_path)

    digest = sha256_file(cache_path)
    if expected_digest is not None and digest != expected_digest:
        raise AdapterError(
            f"Archive for {source.repo}@{source.commit} at {cache_path} does not "
            f"match the expected digest.\n"
            f"  Expected: {expected_digest}\n"
            f"  Actual:   {digest}\n"
            f"  How to fix: verify the digest recorded in the lockfile is "
            f"correct, or delete {cache_path} and re-fetch if the archive is "
            f"suspected to be corrupt or tampered with."
        )

    tree_root = _extract(source, cache_path)
    return tree_root, digest


def _download(source: AdapterSource, cache_path: Path) -> None:
    """Download the tarball to `cache_path` via a `.part` file, then rename."""
    url = tarball_url(source)
    part_path = cache_path.with_suffix(cache_path.suffix + ".part")
    try:
        with (
            urllib.request.urlopen(  # noqa: S310
                url, timeout=_DOWNLOAD_TIMEOUT_SECONDS
            ) as response,
            part_path.open("wb") as part_file,
        ):
            shutil.copyfileobj(response, part_file)
        part_path.rename(cache_path)
    except (urllib.error.URLError, OSError) as exc:
        part_path.unlink(missing_ok=True)
        raise AdapterError(
            f"Failed to fetch {source.repo}@{source.commit} from {url}: {exc}.\n"
            f"  How to fix: check network connectivity and that the commit "
            f"exists in {source.repo}, or pre-populate the cache by placing "
            f"the tarball at {cache_path}."
        ) from exc


def _extract(source: AdapterSource, cache_path: Path) -> Path:
    """Extract `cache_path` to a fresh temp dir and return the inner tree root."""
    extract_dir = Path(tempfile.mkdtemp(prefix="reinicorn-skillset-"))
    try:
        with tarfile.open(cache_path) as tar:
            tar.extractall(path=extract_dir, filter="data")
    except (tarfile.TarError, OSError) as exc:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise AdapterError(
            f"Failed to extract archive {cache_path} for "
            f"{source.repo}@{source.commit}: {exc}.\n"
            f"  How to fix: the archive may be corrupt or contain unsafe "
            f"members; delete {cache_path} and re-fetch, or inspect the "
            f"tarball contents."
        ) from exc

    entries = list(extract_dir.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise AdapterError(
            f"Archive {cache_path} for {source.repo}@{source.commit} did not "
            f"extract to a single top-level directory (found "
            f"{[e.name for e in entries]!r} under {extract_dir}).\n"
            f"  How to fix: verify the archive matches the expected GitHub "
            f"codeload tarball layout (one 'owner-repo-sha/' directory)."
        )
    return entries[0]
