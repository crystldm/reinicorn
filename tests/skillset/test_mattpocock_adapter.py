"""Schema-level tests for the bundled `mattpocock-skills` adapter definition.

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
def mattpocock() -> Adapter:
    adapter_dir = _adapters_dir() / "mattpocock-skills"
    assert adapter_dir.is_dir(), f"bundled adapter missing at {adapter_dir}"
    return load_adapter(adapter_dir)


def test_loads(mattpocock: Adapter) -> None:
    assert mattpocock.name == "mattpocock-skills"
    assert mattpocock.source.repo == "mattpocock/skills"
    assert mattpocock.source.commit == "6acc160e4e0cd062dbbbd7a1b26ae92855edf07e"
    assert len(mattpocock.skills) == 12


def test_patch_targets_are_consistent(mattpocock: Adapter) -> None:
    validate_patch_targets(mattpocock)  # raises AdapterError on contradiction


def test_skills_map_upstream_paths_to_same_named_skills(mattpocock: Adapter) -> None:
    for upstream, installed in mattpocock.skills.items():
        assert upstream in (
            f"skills/engineering/{installed}",
            f"skills/productivity/{installed}",
        ), f"{upstream} should install as skills/(engineering|productivity)/{installed}"
        assert Path(upstream).name == installed


def test_appends_target_installed_skills(mattpocock: Adapter) -> None:
    installed = set(mattpocock.skills.values())
    for name in mattpocock.appends:
        assert name in installed, f"appends.{name} is not an installed skill"


def test_patches_touch_only_declared_skill_trees(mattpocock: Adapter) -> None:
    prefixes = tuple(f"{upstream}/" for upstream in mattpocock.skills)
    for rel_patch in mattpocock.patches:
        text = (mattpocock.root / rel_patch).read_text()
        touched = patch_touched_paths(text)
        assert touched, f"{rel_patch} touches no files"
        for path in touched:
            assert path.startswith(prefixes), (
                f"{rel_patch} touches '{path}', outside the declared skills"
            )


def test_patches_are_listed_in_alphabetical_order(mattpocock: Adapter) -> None:
    assert list(mattpocock.patches) == sorted(mattpocock.patches)


def test_excludes_are_inside_declared_skill_trees(mattpocock: Adapter) -> None:
    prefixes = tuple(f"{upstream}/" for upstream in mattpocock.skills)
    for rel in mattpocock.excludes:
        assert rel.startswith(prefixes), (
            f"excludes entry '{rel}' is outside the declared skills"
        )


def test_files_land_inside_declared_skills_or_at_the_root(mattpocock: Adapter) -> None:
    installed = set(mattpocock.skills.values())
    for installed_path in mattpocock.files:
        head = Path(installed_path).parts[0]
        assert head in installed or head == installed_path, (
            f"files entry '{installed_path}' is neither a root file nor inside "
            f"an installed skill"
        )


def test_attribution_is_installed_at_the_skills_root(mattpocock: Adapter) -> None:
    assert "ATTRIBUTION.md" in mattpocock.files
    text = (mattpocock.root / mattpocock.files["ATTRIBUTION.md"]).read_text()
    assert "MIT License" in text
    assert "mattpocock/skills" in text


def test_wiring_references_installed_skills(mattpocock: Adapter) -> None:
    installed = set(mattpocock.skills.values())
    assert set(mattpocock.wiring) == {"spec", "plan"}
    for doc_type, entry in mattpocock.wiring.items():
        for skill in entry.skills:
            assert skill in installed, (
                f"wiring.{doc_type} references uninstalled skill '{skill}'"
            )


def test_to_spec_patch_reroutes_to_rcorn_spec_create(mattpocock: Adapter) -> None:
    text = (mattpocock.root / "patches/to-spec.patch").read_text()
    assert "rcorn spec create" in text


def test_wiring_maps_spec_and_plan_to_the_expected_skill_order(
    mattpocock: Adapter,
) -> None:
    assert mattpocock.wiring["spec"].skills == ("grill-with-docs", "to-spec")
    assert mattpocock.wiring["plan"].skills == ("to-tickets", "wayfinder", "implement")
