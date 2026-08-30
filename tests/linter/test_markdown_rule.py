"""Tests for the docs/markdown external lint rule (linters/rules/docs/markdown.sh)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "linters" / "rules" / "docs" / "markdown.sh"
RUMDL_CONFIG = REPO_ROOT / ".rumdl.toml"

BAD_FENCE = "# Doc\n\nText.\n\n```\ncode with no language\n```\n"
CLEAN = "# Doc\n\nA clean paragraph.\n"
HOUSE_STYLE = (
    "# Doc\n\n**Bold lead-in.** This long line goes on and on and on and on "
    "and on and on and on and on and on well past eighty characters.\n"
)


def make_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(RUMDL_CONFIG, root / ".rumdl.toml")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def run_rule(root: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    kwargs = {}
    if env is not None:
        kwargs["env"] = env
    return subprocess.run(
        [str(SCRIPT), str(root)], capture_output=True, text=True, check=False, **kwargs
    )


def test_violation_reported_in_framework_format(tmp_path: Path):
    root = make_project(tmp_path)
    (root / "bad.md").write_text(BAD_FENCE)
    result = run_rule(root)
    assert result.returncode == 1
    assert "bad.md:5 — [MD040]" in result.stdout


def test_clean_project_passes(tmp_path: Path):
    root = make_project(tmp_path)
    (root / "good.md").write_text(CLEAN)
    result = run_rule(root)
    assert result.returncode == 0
    assert "[MD" not in result.stdout


def test_house_style_produces_no_violations(tmp_path: Path):
    """MD036 (bold lead-in) and MD013 (line length) are disabled by config."""
    root = make_project(tmp_path)
    (root / "style.md").write_text(HOUSE_STYLE)
    result = run_rule(root)
    assert result.returncode == 0
    assert "[MD" not in result.stdout


def test_excluded_and_gitignored_paths_are_silent(tmp_path: Path):
    root = make_project(tmp_path)
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.md").write_text(BAD_FENCE)
    (root / ".claude" / "worktrees").mkdir(parents=True)
    (root / ".claude" / "worktrees" / "wt.md").write_text(BAD_FENCE)
    (root / ".gitignore").write_text("ignored/\nkb/\n")
    (root / "ignored").mkdir()
    (root / "ignored" / "gen.md").write_text(BAD_FENCE)
    (root / "good.md").write_text(CLEAN)
    result = run_rule(root)
    assert result.returncode == 0
    assert "[MD" not in result.stdout


def test_kb_clone_is_linted_with_prefixed_paths(tmp_path: Path):
    """kb/ is gitignored in the outer repo but must still be linted."""
    root = make_project(tmp_path)
    (root / ".gitignore").write_text("kb/\n")
    kb = root / "kb"
    kb.mkdir()
    subprocess.run(["git", "init", "-q", str(kb)], check=True)
    (kb / "doc.md").write_text(BAD_FENCE)
    result = run_rule(root)
    assert result.returncode == 1
    assert "kb/doc.md:5 — [MD040]" in result.stdout


def test_tool_absent_skips_with_hint(tmp_path: Path):
    root = make_project(tmp_path)
    (root / "bad.md").write_text(BAD_FENCE)
    # PATH without the project venv or uv: rumdl unresolvable either way.
    result = run_rule(root, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert result.returncode == 0
    assert "rumdl not found — skipping. Install with: pip install rumdl" in result.stdout
