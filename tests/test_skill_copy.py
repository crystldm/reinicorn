"""Tests that rcorn init copies the correct unified skill set."""

from __future__ import annotations

from pathlib import Path


def test_init_copies_expected_skills(tmp_path: Path):
    """rcorn init copies directory-based skills, not deleted standalone files."""
    from reinicorn.commands.init import _copy_skills
    from reinicorn.git import reinicorn_root

    r_root = reinicorn_root()
    target = tmp_path / "repo"
    target.mkdir()

    _copy_skills(r_root, target)

    skills_dir = target / ".agents" / "skills"
    assert skills_dir.is_dir()

    # .claude/skills must be a symlink resolving to the canonical .agents/skills
    link = target / ".claude" / "skills"
    assert link.is_symlink()
    assert link.resolve() == skills_dir.resolve()

    # Deleted standalone files must NOT be present
    assert not (skills_dir / "create-exec-plan.md").exists()
    assert not (skills_dir / "review-pr.md").exists()

    # Expected directory-based skills must exist
    expected_dirs = [
        "brainstorming",
        "writing-plans",
        "executing-plans",
        "requesting-code-review",
        "test-driven-development",
        "systematic-debugging",
        "verification-before-completion",
        "receiving-code-review",
        "dispatching-parallel-agents",
        "subagent-driven-development",
        "finishing-a-development-branch",
        "using-git-worktrees",
        "writing-skills",
        "populate-agents-md",
        "using-reinicorn",
    ]
    for name in expected_dirs:
        assert (skills_dir / name).is_dir(), f"Missing skill directory: {name}"

    # ATTRIBUTION.md must be copied
    assert (skills_dir / "ATTRIBUTION.md").is_file()

    # Merged content must be present in target skills
    wp = (skills_dir / "writing-plans" / "SKILL.md").read_text()
    assert "Reinicorn Integration" in wp

    rcr = (skills_dir / "requesting-code-review" / "SKILL.md").read_text()
    assert "Reinicorn PR Review" in rcr


def test_link_leaves_real_claude_skills_dir_untouched(tmp_path: Path):
    """A pre-existing REAL .claude/skills dir is never deleted or replaced."""
    from reinicorn.commands.init import _copy_skills
    from reinicorn.git import reinicorn_root

    r_root = reinicorn_root()
    target = tmp_path / "repo"
    target.mkdir()
    existing = target / ".claude" / "skills"
    existing.mkdir(parents=True)
    sentinel = existing / "my-user-skill.md"
    sentinel.write_text("# User content\n")

    _copy_skills(r_root, target)

    # Canonical location still populated
    assert (target / ".agents/skills/using-reinicorn/SKILL.md").is_file()
    assert not (target / ".agents/skills/using-reins").exists()

    # Pre-existing real dir left in place: still a real dir, sentinel intact
    assert not existing.is_symlink()
    assert existing.is_dir()
    assert sentinel.read_text() == "# User content\n"


def test_link_falls_back_to_copy_when_symlinks_unavailable(
    tmp_path: Path, monkeypatch,
):
    """When symlink_to raises OSError, skills are copied to .claude/skills."""
    from reinicorn.commands.init import _copy_skills
    from reinicorn.git import reinicorn_root

    def _no_symlinks(self, *args, **kwargs):
        raise OSError("symlinks unavailable")

    monkeypatch.setattr(Path, "symlink_to", _no_symlinks)

    r_root = reinicorn_root()
    target = tmp_path / "repo"
    target.mkdir()

    _copy_skills(r_root, target)

    # Canonical location populated
    assert (target / ".agents/skills/using-reinicorn/SKILL.md").is_file()
    assert not (target / ".agents/skills/using-reins").exists()

    # Fallback: .claude/skills is a REAL dir with a full copy
    link = target / ".claude" / "skills"
    assert not link.is_symlink()
    assert link.is_dir()
    assert (link / "using-reinicorn" / "SKILL.md").is_file()
