"""refs.py: the depends_on machinery shared by the lint and the push gate."""

from __future__ import annotations

import pytest

from reinicorn.refs import path_in_dir


@pytest.mark.parametrize(
    ("path", "dir_path", "expected"),
    [
        ("reinicorn/specs/x.md", "specs", True),
        ("reinicorn/specs/drafts/x.md", "specs", True),
        # A nested dir_path spans two components — one membership test on
        # the parent list cannot find it.
        ("reinicorn/architecture/specs/x.md", "architecture/specs", True),
        ("reinicorn/architecture/x.md", "architecture/specs", False),
        ("reinicorn/specs/x.md", "architecture/specs", False),
        # Component match, not substring: lookalikes and the file's own
        # name do not count.
        ("reinicorn/my-specs/x.md", "specs", False),
        ("reinicorn/exec-plans/active/b/specs", "specs", False),
    ],
)
def test_path_in_dir(path, dir_path, expected):
    assert path_in_dir(path, dir_path) is expected
