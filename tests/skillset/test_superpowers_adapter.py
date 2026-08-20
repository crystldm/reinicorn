"""Schema-level tests for the bundled `superpowers` adapter definition.

These never touch the network: they validate the checked-in adapter
definition's shape and internal consistency only. Byte-identity against a
real install is verified manually (see the task's live-verification step).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reinicorn.assets import get_asset_path
from reinicorn.skillset.adapter import Adapter, load_adapter
from reinicorn.skillset.engine import patch_touched_paths, validate_patch_targets


def _adapters_dir() -> Path:
    """The bundled adapters directory (wheel `_data/` or repo root)."""
    bundled = get_asset_path("adapters")
    if bundled is not None:
        return bundled
    return Path(__file__).resolve().parents[2] / "adapters"


@pytest.fixture(scope="module")
def superpowers() -> Adapter:
    adapter_dir = _adapters_dir() / "superpowers"
    assert adapter_dir.is_dir(), f"bundled adapter missing at {adapter_dir}"
    return load_adapter(adapter_dir)


def test_loads(superpowers: Adapter) -> None:
    assert superpowers.name == "superpowers"
    assert superpowers.source.repo == "obra/superpowers"
    assert superpowers.skills


def test_patch_targets_are_consistent(superpowers: Adapter) -> None:
    validate_patch_targets(superpowers)  # raises AdapterError on contradiction


def test_skills_map_upstream_paths_to_same_named_skills(superpowers: Adapter) -> None:
    for upstream, installed in superpowers.skills.items():
        assert upstream == f"skills/{installed}", (
            f"{upstream} should install as skills/{installed}"
        )


def test_appends_target_installed_skills(superpowers: Adapter) -> None:
    installed = set(superpowers.skills.values())
    for name in superpowers.appends:
        assert name in installed, f"appends.{name} is not an installed skill"


def test_patches_touch_only_declared_skill_trees(superpowers: Adapter) -> None:
    prefixes = tuple(f"{upstream}/" for upstream in superpowers.skills)
    for rel_patch in superpowers.patches:
        text = (superpowers.root / rel_patch).read_text()
        touched = patch_touched_paths(text)
        assert touched, f"{rel_patch} touches no files"
        for path in touched:
            assert path.startswith(prefixes), (
                f"{rel_patch} touches '{path}', outside the declared skills"
            )


def test_patches_are_listed_in_alphabetical_order(superpowers: Adapter) -> None:
    assert list(superpowers.patches) == sorted(superpowers.patches)


def test_excludes_are_inside_declared_skill_trees(superpowers: Adapter) -> None:
    prefixes = tuple(f"{upstream}/" for upstream in superpowers.skills)
    for rel in superpowers.excludes:
        assert rel.startswith(prefixes), (
            f"excludes entry '{rel}' is outside the declared skills"
        )


def test_files_land_inside_declared_skills_or_at_the_root(superpowers: Adapter) -> None:
    installed = set(superpowers.skills.values())
    for installed_path in superpowers.files:
        head = Path(installed_path).parts[0]
        assert head in installed or head == installed_path, (
            f"files entry '{installed_path}' is neither a root file nor inside "
            f"an installed skill"
        )


def test_attribution_is_installed_at_the_skills_root(superpowers: Adapter) -> None:
    assert "ATTRIBUTION.md" in superpowers.files
    text = (superpowers.root / superpowers.files["ATTRIBUTION.md"]).read_text()
    assert "MIT License" in text
    assert "obra/superpowers" in text


def test_wiring_references_installed_skills(superpowers: Adapter) -> None:
    installed = set(superpowers.skills.values())
    assert set(superpowers.wiring) == {"spec", "plan"}
    for doc_type, entry in superpowers.wiring.items():
        for skill in entry.skills:
            assert skill in installed, (
                f"wiring.{doc_type} references uninstalled skill '{skill}'"
            )
