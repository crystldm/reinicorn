"""Tests for reinicorn.skillset.adapter."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from reinicorn.skillset.adapter import (
    Adapter,
    AdapterError,
    AdapterSource,
    WiringEntry,
    load_adapter,
)

VALID_YAML = """\
name: demo
source:
  repo: acme/skills
  commit: 0123456789abcdef0123456789abcdef01234567
  annotation: v1.0.0
skills:
  skills/alpha: alpha
  skills/nested/beta: beta
patches:
  - patches/alpha-kb-paths.patch
appends:
  alpha:
    - appends/alpha-reinicorn.md
excludes:
  - skills/alpha/scratch.md
overrides:
  beta/references/template.md: overrides/template.md
files:
  ATTRIBUTION.md: files/ATTRIBUTION.md
wiring:
  spec: [alpha]
  prd:
    skills: [alpha]
    optional: true
"""


def make_adapter_dir(
    tmp_path: Path, yaml_text: str, extra_files: dict[str, str] | None = None
) -> Path:
    """Write adapter.yaml plus any adapter-relative files it references."""
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    (adapter_dir / "adapter.yaml").write_text(yaml_text)
    for rel, content in (extra_files or {}).items():
        path = adapter_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return adapter_dir


VALID_EXTRA_FILES = {
    "patches/alpha-kb-paths.patch": "diff --git a/x b/x\n",
    "appends/alpha-reinicorn.md": "## Reinicorn\n",
    "overrides/template.md": "template\n",
    "files/ATTRIBUTION.md": "attribution\n",
}


def test_happy_path_parses_full_shape(tmp_path: Path) -> None:
    adapter_dir = make_adapter_dir(tmp_path, VALID_YAML, VALID_EXTRA_FILES)

    adapter = load_adapter(adapter_dir)

    assert isinstance(adapter, Adapter)
    assert adapter.name == "demo"
    assert adapter.source == AdapterSource(
        repo="acme/skills",
        commit="0123456789abcdef0123456789abcdef01234567",
        annotation="v1.0.0",
    )
    assert adapter.skills == {
        "skills/alpha": "alpha",
        "skills/nested/beta": "beta",
    }
    assert adapter.patches == ("patches/alpha-kb-paths.patch",)
    assert adapter.appends == {"alpha": ("appends/alpha-reinicorn.md",)}
    assert adapter.excludes == ("skills/alpha/scratch.md",)
    assert adapter.overrides == {
        "beta/references/template.md": "overrides/template.md"
    }
    assert adapter.files == {"ATTRIBUTION.md": "files/ATTRIBUTION.md"}
    assert adapter.wiring == {
        "spec": WiringEntry(skills=("alpha",), optional=False),
        "prd": WiringEntry(skills=("alpha",), optional=True),
    }
    assert adapter.root == adapter_dir


def test_tag_as_pin_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "commit: 0123456789abcdef0123456789abcdef01234567",
        "commit: v5.0.6",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="40-hex commit SHA"):
        load_adapter(adapter_dir)
    with pytest.raises(AdapterError, match="resolve the tag"):
        load_adapter(adapter_dir)


def test_missing_referenced_patch_file_raises_naming_path(tmp_path: Path) -> None:
    extra = {k: v for k, v in VALID_EXTRA_FILES.items() if k != "patches/alpha-kb-paths.patch"}
    adapter_dir = make_adapter_dir(tmp_path, VALID_YAML, extra)

    with pytest.raises(AdapterError, match=re.escape("patches/alpha-kb-paths.patch")):
        load_adapter(adapter_dir)


def test_missing_referenced_append_file_raises_naming_path(tmp_path: Path) -> None:
    extra = {k: v for k, v in VALID_EXTRA_FILES.items() if k != "appends/alpha-reinicorn.md"}
    adapter_dir = make_adapter_dir(tmp_path, VALID_YAML, extra)

    with pytest.raises(AdapterError, match=re.escape("appends/alpha-reinicorn.md")):
        load_adapter(adapter_dir)


def test_missing_referenced_override_file_raises_naming_path(tmp_path: Path) -> None:
    extra = {k: v for k, v in VALID_EXTRA_FILES.items() if k != "overrides/template.md"}
    adapter_dir = make_adapter_dir(tmp_path, VALID_YAML, extra)

    with pytest.raises(AdapterError, match=re.escape("overrides/template.md")):
        load_adapter(adapter_dir)


def test_missing_referenced_files_entry_raises_naming_path(tmp_path: Path) -> None:
    extra = {k: v for k, v in VALID_EXTRA_FILES.items() if k != "files/ATTRIBUTION.md"}
    adapter_dir = make_adapter_dir(tmp_path, VALID_YAML, extra)

    with pytest.raises(AdapterError, match=re.escape("files/ATTRIBUTION.md")):
        load_adapter(adapter_dir)


def test_wiring_shorthand_and_expanded_forms_parse_to_wiring_entry(
    tmp_path: Path,
) -> None:
    adapter_dir = make_adapter_dir(tmp_path, VALID_YAML, VALID_EXTRA_FILES)

    adapter = load_adapter(adapter_dir)

    assert adapter.wiring["spec"] == WiringEntry(skills=("alpha",), optional=False)
    assert adapter.wiring["prd"] == WiringEntry(skills=("alpha",), optional=True)


def test_empty_skills_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "skills:\n  skills/alpha: alpha\n  skills/nested/beta: beta\n",
        "skills: {}\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="skills"):
        load_adapter(adapter_dir)


def test_unknown_top_level_key_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML + "bogus: true\n"
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="bogus"):
        load_adapter(adapter_dir)


def test_missing_adapter_yaml_raises(tmp_path: Path) -> None:
    adapter_dir = tmp_path / "empty-adapter"
    adapter_dir.mkdir()

    with pytest.raises(AdapterError, match=re.escape("adapter.yaml")):
        load_adapter(adapter_dir)


def test_invalid_yaml_raises(tmp_path: Path) -> None:
    adapter_dir = make_adapter_dir(tmp_path, "not: [valid: yaml", {})

    with pytest.raises(AdapterError):
        load_adapter(adapter_dir)


def test_non_mapping_yaml_raises(tmp_path: Path) -> None:
    adapter_dir = make_adapter_dir(tmp_path, "- just\n- a\n- list\n", {})

    with pytest.raises(AdapterError):
        load_adapter(adapter_dir)


def test_repo_not_owner_slash_name_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace("repo: acme/skills", "repo: not-a-repo-slug")
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=re.escape("source.repo")):
        load_adapter(adapter_dir)


def test_appends_path_traversal_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "    - appends/alpha-reinicorn.md",
        "    - ../escape.md",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)
    (tmp_path / "escape.md").write_text("nope\n")

    with pytest.raises(AdapterError, match=r"\.\."):
        load_adapter(adapter_dir)


def test_appends_absolute_path_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "    - appends/alpha-reinicorn.md",
        "    - /etc/passwd",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError):
        load_adapter(adapter_dir)


def test_wiring_entry_requires_non_empty_skills_list(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace("  spec: [alpha]\n", "  spec: []\n")
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="wiring"):
        load_adapter(adapter_dir)


def test_wiring_entry_skills_must_be_strings(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace("  spec: [alpha]\n", "  spec: [1, 2]\n")
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="wiring"):
        load_adapter(adapter_dir)


def test_missing_name_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace("name: demo\n", "")
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="name"):
        load_adapter(adapter_dir)


def test_source_not_a_mapping_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "source:\n  repo: acme/skills\n  commit: "
        "0123456789abcdef0123456789abcdef01234567\n  annotation: v1.0.0\n",
        "source: not-a-mapping\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="source"):
        load_adapter(adapter_dir)


def test_unknown_source_key_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "  annotation: v1.0.0\n", "  annotation: v1.0.0\n  bogus: true\n"
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="bogus"):
        load_adapter(adapter_dir)


def test_missing_annotation_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace("  annotation: v1.0.0\n", "")
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="annotation"):
        load_adapter(adapter_dir)


def test_skills_entry_with_non_string_value_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "  skills/alpha: alpha\n", "  skills/alpha: 123\n"
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="skills"):
        load_adapter(adapter_dir)


def test_patches_omitted_defaults_empty(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "patches:\n  - patches/alpha-kb-paths.patch\n", ""
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    adapter = load_adapter(adapter_dir)

    assert adapter.patches == ()


def test_patches_not_a_list_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "patches:\n  - patches/alpha-kb-paths.patch\n", "patches: not-a-list\n"
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="patches"):
        load_adapter(adapter_dir)


def test_appends_omitted_defaults_empty(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "appends:\n  alpha:\n    - appends/alpha-reinicorn.md\n", ""
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    adapter = load_adapter(adapter_dir)

    assert adapter.appends == {}


def test_appends_not_a_mapping_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "appends:\n  alpha:\n    - appends/alpha-reinicorn.md\n",
        "appends: not-a-mapping\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="appends"):
        load_adapter(adapter_dir)


def test_appends_entry_empty_list_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "appends:\n  alpha:\n    - appends/alpha-reinicorn.md\n",
        "appends:\n  alpha: []\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="appends"):
        load_adapter(adapter_dir)


def test_excludes_omitted_defaults_empty(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "excludes:\n  - skills/alpha/scratch.md\n", ""
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    adapter = load_adapter(adapter_dir)

    assert adapter.excludes == ()


def test_excludes_not_a_list_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "excludes:\n  - skills/alpha/scratch.md\n", "excludes: not-a-list\n"
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="excludes"):
        load_adapter(adapter_dir)


def test_overrides_omitted_defaults_empty(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "overrides:\n  beta/references/template.md: overrides/template.md\n", ""
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    adapter = load_adapter(adapter_dir)

    assert adapter.overrides == {}


def test_overrides_not_a_mapping_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "overrides:\n  beta/references/template.md: overrides/template.md\n",
        "overrides: not-a-mapping\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="overrides"):
        load_adapter(adapter_dir)


def test_overrides_entry_with_non_string_value_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "overrides:\n  beta/references/template.md: overrides/template.md\n",
        "overrides:\n  beta/references/template.md: 123\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="overrides"):
        load_adapter(adapter_dir)


def test_files_omitted_defaults_empty(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "files:\n  ATTRIBUTION.md: files/ATTRIBUTION.md\n", ""
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    adapter = load_adapter(adapter_dir)

    assert adapter.files == {}


def test_files_not_a_mapping_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "files:\n  ATTRIBUTION.md: files/ATTRIBUTION.md\n", "files: not-a-mapping\n"
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="files"):
        load_adapter(adapter_dir)


def test_wiring_omitted_defaults_empty(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "wiring:\n  spec: [alpha]\n  prd:\n    skills: [alpha]\n    optional: true\n",
        "",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    adapter = load_adapter(adapter_dir)

    assert adapter.wiring == {}


def test_wiring_not_a_mapping_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "wiring:\n  spec: [alpha]\n  prd:\n    skills: [alpha]\n    optional: true\n",
        "wiring: not-a-mapping\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="wiring"):
        load_adapter(adapter_dir)


def test_wiring_entry_unknown_key_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "  prd:\n    skills: [alpha]\n    optional: true\n",
        "  prd:\n    skills: [alpha]\n    optional: true\n    bogus: 1\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="bogus"):
        load_adapter(adapter_dir)


def test_wiring_entry_optional_must_be_bool(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "    optional: true\n", "    optional: not-a-bool\n"
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="optional"):
        load_adapter(adapter_dir)


def test_wiring_entry_skills_key_missing_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "  prd:\n    skills: [alpha]\n    optional: true\n",
        "  prd:\n    optional: true\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="skills"):
        load_adapter(adapter_dir)


def test_wiring_entry_not_list_or_mapping_raises(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace("  spec: [alpha]\n", "  spec: 123\n")
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match="wiring"):
        load_adapter(adapter_dir)


# === Gap 1a: overrides key path safety (absolute/parent-dir escape) ===


def test_overrides_key_absolute_path_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "overrides:\n  beta/references/template.md: overrides/template.md\n",
        "overrides:\n  /etc/passwd: overrides/template.md\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=r"overrides.*absolute"):
        load_adapter(adapter_dir)


def test_overrides_key_parent_dir_escape_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "overrides:\n  beta/references/template.md: overrides/template.md\n",
        "overrides:\n  ../escape.md: overrides/template.md\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=r"overrides.*\.\."):
        load_adapter(adapter_dir)


def test_files_key_absolute_path_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "files:\n  ATTRIBUTION.md: files/ATTRIBUTION.md\n",
        "files:\n  /etc/passwd: files/ATTRIBUTION.md\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=r"files.*absolute"):
        load_adapter(adapter_dir)


def test_files_key_parent_dir_escape_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "files:\n  ATTRIBUTION.md: files/ATTRIBUTION.md\n",
        "files:\n  ../escape.md: files/ATTRIBUTION.md\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=r"files.*\.\."):
        load_adapter(adapter_dir)


# === Gap 1b: skills value path safety (single component, no /, absolute, ..) ===


def test_skills_value_absolute_path_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "  skills/alpha: alpha\n", "  skills/alpha: /etc/passwd\n"
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=r"skills.*absolute"):
        load_adapter(adapter_dir)


def test_skills_value_parent_dir_escape_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "  skills/alpha: alpha\n", "  skills/alpha: ../escape\n"
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=r"skills.*\.\."):
        load_adapter(adapter_dir)


def test_skills_value_nested_path_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "  skills/alpha: alpha\n", "  skills/alpha: nested/alpha\n"
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=r"skills.*single.*component"):
        load_adapter(adapter_dir)


def test_skills_duplicate_installed_name_rejected(tmp_path: Path) -> None:
    """Two upstream dirs installing to the same name must fail at load time,
    naming the duplicate — not later as a raw FileExistsError out of
    `shutil.copytree` when the engine stages them."""
    yaml_text = """\
name: demo
source:
  repo: acme/skills
  commit: 0123456789abcdef0123456789abcdef01234567
  annotation: v1.0.0
skills:
  skills/alpha: shared
  skills/nested/beta: shared
"""
    adapter_dir = make_adapter_dir(tmp_path, yaml_text)

    with pytest.raises(AdapterError, match="shared") as exc_info:
        load_adapter(adapter_dir)
    message = str(exc_info.value)
    assert "skills/alpha" in message
    assert "skills/nested/beta" in message


# === Gap 2: skills key (upstream path) emptiness check ===


def test_skills_key_empty_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "skills:\n  skills/alpha: alpha\n", 'skills:\n  "": alpha\n'
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=r"skills.*empty"):
        load_adapter(adapter_dir)


# === Gap 3: wiring error message split (empty list vs non-string) ===


def test_wiring_skills_empty_list_clear_message(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace("  spec: [alpha]\n", "  spec: []\n")
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=r"must be a non-empty list"):
        load_adapter(adapter_dir)


def test_wiring_skills_non_string_element_clear_message(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace("  spec: [alpha]\n", "  spec: [1]\n")
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=r"must be strings"):
        load_adapter(adapter_dir)


# === T13: upstream-relative path safety (excludes entries, skills keys) ===


def test_excludes_entry_absolute_path_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "excludes:\n  - skills/alpha/scratch.md\n",
        "excludes:\n  - /etc/passwd\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=re.escape("/etc/passwd")):
        load_adapter(adapter_dir)


def test_excludes_entry_parent_dir_escape_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "excludes:\n  - skills/alpha/scratch.md\n",
        "excludes:\n  - ../x\n",
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=re.escape("../x")):
        load_adapter(adapter_dir)


def test_skills_key_parent_dir_escape_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "  skills/alpha: alpha\n", "  ../evil: ok-name\n"
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=re.escape("../evil")):
        load_adapter(adapter_dir)


def test_skills_key_absolute_path_rejected(tmp_path: Path) -> None:
    yaml_text = VALID_YAML.replace(
        "  skills/alpha: alpha\n", "  /etc/passwd: ok-name\n"
    )
    adapter_dir = make_adapter_dir(tmp_path, yaml_text, VALID_EXTRA_FILES)

    with pytest.raises(AdapterError, match=re.escape("/etc/passwd")):
        load_adapter(adapter_dir)
