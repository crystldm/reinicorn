"""Guard the published sdist contents.

The wheel has an explicit force-include allowlist, but the sdist is easy to
regress: hatchling's default sweeps in every git-tracked path. This test builds
the real sdist and asserts the private kb/ tree and dev material stay out while
everything needed to rebuild the wheel stays in.
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Top-level directories that must never appear in the published source archive:
# the private knowledge base, JS build output, and local dev/tooling state.
FORBIDDEN_TOP_LEVEL = {
    "kb",
    "presentation",
    "node_modules",
    ".superpowers",
    ".github",
    ".claude",
    ".cursor",
    ".reinicorn",
}

# Paths a source build needs to rebuild the wheel (asset sources force-included
# into the wheel) plus the package and its tests.
REQUIRED_PREFIXES = (
    "src/reinicorn/",
    "tests/",
    ".agents/skills/",
    "hooks/",
    "editor-hooks/",
    "linters/",
    "templates/AGENTS.md",
)


@pytest.fixture(scope="module")
def sdist_member_relpaths(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    """Build the sdist once and return member paths with the pkg dir stripped."""
    if shutil.which("uv") is None:
        pytest.skip("uv not available to build the sdist")

    out_dir = tmp_path_factory.mktemp("sdist")
    result = subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"uv build --sdist failed in this environment:\n{result.stderr}")

    archives = list(out_dir.glob("*.tar.gz"))
    assert len(archives) == 1, f"expected one sdist, found {archives}"

    with tarfile.open(archives[0]) as tar:
        names = tar.getnames()

    # Every entry is "<pkg>-<version>/<relpath>"; drop the top component.
    return ["/".join(name.split("/")[1:]) for name in names if "/" in name]


def test_sdist_excludes_private_and_dev_trees(
    sdist_member_relpaths: list[str],
) -> None:
    top_level = {r.split("/")[0] for r in sdist_member_relpaths if r}
    leaked = top_level & FORBIDDEN_TOP_LEVEL
    assert not leaked, f"sdist leaked private/dev directories: {sorted(leaked)}"


def test_sdist_contains_everything_needed_to_build(
    sdist_member_relpaths: list[str],
) -> None:
    for prefix in REQUIRED_PREFIXES:
        assert any(r.startswith(prefix) for r in sdist_member_relpaths), (
            f"sdist is missing required build input: {prefix}"
        )
