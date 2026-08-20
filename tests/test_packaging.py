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
import zipfile
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
    "adapters/",
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


@pytest.fixture(scope="module")
def wheel_data_skill_dirs(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    """Build the wheel from a clean `git worktree` at HEAD and return the
    top-level directory names under `reinicorn/_data/skills/`.

    The wheel's `force-include` maps `.agents/skills` straight off the
    filesystem (unlike the sdist, it is not git-filtered), so building
    from REPO_ROOT directly would sweep in whatever is actually on disk —
    including gitignored, adapter-installed skills dogfed into this very
    checkout (`.agents/skills/*` is gitignored except `using-reinicorn/`
    and `populate-agents-md/`, see .gitignore). A worktree checked out at
    HEAD reflects only what's git-tracked, matching a real release build
    and staying green regardless of what's dogfed locally or in CI.
    """
    if shutil.which("uv") is None:
        pytest.skip("uv not available to build the wheel")

    worktree_dir = tmp_path_factory.mktemp("wheel_worktree") / "src"
    add_result = subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree_dir), "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if add_result.returncode != 0:
        pytest.skip(f"git worktree add failed in this environment:\n{add_result.stderr}")

    try:
        out_dir = tmp_path_factory.mktemp("wheel_out")
        build_result = subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
            cwd=worktree_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if build_result.returncode != 0:
            pytest.skip(f"uv build --wheel failed in this environment:\n{build_result.stderr}")

        wheels = list(out_dir.glob("*.whl"))
        assert len(wheels) == 1, f"expected one wheel, found {wheels}"

        with zipfile.ZipFile(wheels[0]) as zf:
            names = zf.namelist()
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_dir)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    prefix = "reinicorn/_data/skills/"
    return sorted(
        {
            name[len(prefix) :].split("/")[0]
            for name in names
            if name.startswith(prefix) and len(name) > len(prefix)
        }
    )


def test_wheel_data_skills_contains_only_native_skills(
    wheel_data_skill_dirs: list[str],
) -> None:
    """The wheel ships only the two native (non-adapter) skills. Anything
    else means a dogfed, adapter-installed skill leaked into the build —
    see `wheel_data_skill_dirs`'s docstring for why this must build from a
    clean worktree rather than REPO_ROOT directly."""
    assert wheel_data_skill_dirs == ["populate-agents-md", "using-reinicorn"]
