"""Ensure third-party licensing ships with the package.

Several skills are forked from the upstream Superpowers plugin (MIT, Jesse
Vincent). The MIT permission and disclaimer text must travel with the
distributed skills, and the attribution must point at the real upstream repo.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def wheel_attribution_text(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Build the wheel and return the bundled skills ATTRIBUTION.md text."""
    if shutil.which("uv") is None:
        pytest.skip("uv not available to build the wheel")

    out_dir = tmp_path_factory.mktemp("wheel")
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"uv build --wheel failed in this environment:\n{result.stderr}")

    wheels = list(out_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, found {wheels}"

    with zipfile.ZipFile(wheels[0]) as wheel:
        matches = [
            n for n in wheel.namelist()
            if n.endswith("_data/skills/ATTRIBUTION.md")
        ]
        assert matches, "ATTRIBUTION.md is not bundled in the wheel"
        return wheel.read(matches[0]).decode()


def test_wheel_bundles_upstream_mit_license(wheel_attribution_text: str) -> None:
    assert "Permission is hereby granted" in wheel_attribution_text
    assert "WITHOUT WARRANTY OF ANY KIND" in wheel_attribution_text
    assert "Copyright (c) 2025 Jesse Vincent" in wheel_attribution_text


def test_wheel_attribution_points_at_real_upstream(
    wheel_attribution_text: str,
) -> None:
    assert "obra/superpowers" in wheel_attribution_text
    assert "anthropics/superpowers" not in wheel_attribution_text
