"""Tests for reins.kb_seed — clean kb template generation."""

from __future__ import annotations

from pathlib import Path

from reinicorn.doc_types import REGISTRY
from reinicorn.kb_seed import generate_seed_tree


def test_generate_seed_tree_creates_registry_dirs(tmp_path: Path):
    """Seed tree creates a dir for every unique dir_path in the registry."""
    generate_seed_tree(tmp_path, repo_slug="my-project")
    scope = tmp_path / "my-project"
    assert scope.is_dir()
    # Every unique dir_path from the registry (except ".") should exist
    for dt in REGISTRY.values():
        if dt.dir_path != ".":
            assert (scope / dt.dir_path).is_dir(), f"Missing {dt.dir_path}/"


def test_generate_seed_tree_creates_structural_dirs(tmp_path: Path):
    """Seed tree creates structural dirs not in the registry (architecture)."""
    generate_seed_tree(tmp_path, repo_slug="my-project")
    scope = tmp_path / "my-project"
    assert (scope / "architecture").is_dir()


def test_generate_seed_tree_creates_golden_principles(tmp_path: Path):
    """Seed tree includes an empty golden-principles.md template."""
    generate_seed_tree(tmp_path, repo_slug="my-project")
    gp = tmp_path / "my-project" / "golden-principles.md"
    assert gp.is_file()
    content = gp.read_text()
    assert "Golden Principles" in content
    # Should NOT contain reins-specific content
    assert "reins" not in content.lower()


def test_generate_seed_tree_creates_exec_plan_template(tmp_path: Path):
    """Seed tree includes exec-plan template files."""
    generate_seed_tree(tmp_path, repo_slug="my-project")
    plan_dir = REGISTRY["plan"].dir_path
    template = tmp_path / "my-project" / plan_dir / "_template"
    assert template.is_dir()
    assert (template / "plan.md").is_file()
    assert not (template / "progress.md").exists()
    assert not (template / "decisions.md").exists()
    plan = (template / "plan.md").read_text()
    # Required sections from the registry should appear
    for section in REGISTRY["plan"].required_sections:
        assert f"## {section}" in plan


def test_generate_seed_tree_creates_gitignore(tmp_path: Path):
    """Seed tree includes a root .gitignore."""
    generate_seed_tree(tmp_path, repo_slug="my-project")
    gi = tmp_path / ".gitignore"
    assert gi.is_file()


def test_generate_seed_tree_creates_quality_scores(tmp_path: Path):
    """Seed tree includes quality-scores.md."""
    generate_seed_tree(tmp_path, repo_slug="my-project")
    qs = tmp_path / "my-project" / "quality-scores.md"
    assert qs.is_file()


def test_seed_creates_drafts_dir_for_gated_types(tmp_path: Path):
    generate_seed_tree(tmp_path, "myrepo")
    assert (tmp_path / "myrepo" / "specs" / "drafts" / ".gitkeep").is_file()


def test_seed_creates_scope_readme_map(tmp_path: Path) -> None:
    generate_seed_tree(tmp_path, "my-project")
    text = (tmp_path / "my-project" / "README.md").read_text()
    # Assert the map's meaningful contract rather than an exact blob: it names the
    # scope and points at every navigable KB location plus the sync/publish flow.
    assert text.startswith("# my-project knowledge base\n")
    for location in (
        "golden-principles.md",
        "architecture/",
        "specs/",
        "prds/",
        "exec-plans/active/",
        "quality-scores.md",
        "tech-debt/",
    ):
        assert location in text
    assert "rcorn kb sync" in text
    assert "rcorn kb publish" in text
    assert "rcorn <type> create" in text


def test_seed_preserves_existing_scope_readme_bytes(tmp_path: Path) -> None:
    scope = tmp_path / "my-project"
    scope.mkdir()
    readme = scope / "README.md"
    original = b"# Team map\n"
    readme.write_bytes(original)

    generate_seed_tree(tmp_path, "my-project")

    assert readme.read_bytes() == original


def test_seed_preserves_dangling_scope_readme_symlink(tmp_path: Path) -> None:
    scope = tmp_path / "my-project"
    scope.mkdir()
    readme = scope / "README.md"
    readme.symlink_to("team-map.md")

    generate_seed_tree(tmp_path, "my-project")

    assert readme.is_symlink()
    assert readme.readlink() == Path("team-map.md")
    assert not (scope / "team-map.md").exists()
