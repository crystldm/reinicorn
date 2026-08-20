"""Tests for reinicorn.skillset.engine."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from reinicorn.manifest import sha256_file
from reinicorn.skillset import engine
from reinicorn.skillset.adapter import Adapter, AdapterError, load_adapter

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "upstream-tree"

# A real unified diff against the fixture's exact skills/alpha/SKILL.md
# content, rewriting "docs/plans/" to "kb/acme-skills/exec-plans/". Generated
# with `git diff --no-index` and inlined per the task brief's instructions.
# Built with explicit "\n".join so blank *context* lines keep their required
# leading space (a bare blank line is not a valid unified-diff context line).
ALPHA_KB_PATHS_PATCH = "\n".join([
    "diff --git a/skills/alpha/SKILL.md b/skills/alpha/SKILL.md",
    "index 8c7baf6..1c269fe 100644",
    "--- a/skills/alpha/SKILL.md",
    "+++ b/skills/alpha/SKILL.md",
    "@@ -5,7 +5,7 @@ description: Alpha skill for planning things.",
    " ",
    " # Alpha",
    " ",
    "-Write your plan to docs/plans/<name>.md and keep it updated.",
    "+Write your plan to kb/acme-skills/exec-plans/<name>.md and keep it updated.",
    " ",
    " ## Steps",
    " ",
    "",
])

# Same hunk shape (so line counts still parse) but the removed context line
# doesn't match the fixture content at all -> git apply fails to find a home.
STALE_ALPHA_PATCH = "\n".join([
    "diff --git a/skills/alpha/SKILL.md b/skills/alpha/SKILL.md",
    "index 8c7baf6..1c269fe 100644",
    "--- a/skills/alpha/SKILL.md",
    "+++ b/skills/alpha/SKILL.md",
    "@@ -5,7 +5,7 @@ description: Alpha skill for planning things.",
    " ",
    " # Alpha",
    " ",
    "-Write your plan to WRONG/path.md and keep it updated.",
    "+Write your plan to kb/acme-skills/exec-plans/<name>.md and keep it updated.",
    " ",
    " ## Steps",
    " ",
    "",
])

# Touches the upstream-relative path that BASE_YAML also excludes.
TOUCH_EXCLUDED_PATCH = """\
diff --git a/skills/alpha/scratch.md b/skills/alpha/scratch.md
index 0000000..1111111 100644
--- a/skills/alpha/scratch.md
+++ b/skills/alpha/scratch.md
@@ -1 +1 @@
-Scratch notes — not shipped.
+Scratch notes — shipped now.
"""

# Touches the upstream path whose installed location BASE_YAML overrides.
TOUCH_OVERRIDDEN_PATCH = """\
diff --git a/skills/nested/beta/references/template.md b/skills/nested/beta/references/template.md
index 0000000..1111111 100644
--- a/skills/nested/beta/references/template.md
+++ b/skills/nested/beta/references/template.md
@@ -1 +1 @@
-# Template
+# Template Renamed
"""

APPEND_BLOCK = "## Reinicorn\n\nUse the wiring doc for skill-doc pairing.\n"
OVERRIDE_TEMPLATE = "# Template (reinicorn override)\n\nReinicorn-authored replacement body.\n"
ATTRIBUTION = "Adapted from acme/skills.\n"

BASE_YAML = """\
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
"""

BASE_EXTRA_FILES = {
    "patches/alpha-kb-paths.patch": ALPHA_KB_PATHS_PATCH,
    "appends/alpha-reinicorn.md": APPEND_BLOCK,
    "overrides/template.md": OVERRIDE_TEMPLATE,
    "files/ATTRIBUTION.md": ATTRIBUTION,
}


def make_adapter(
    tmp_path: Path, yaml_text: str, extra_files: dict[str, str] | None = None
) -> Adapter:
    """Write adapter.yaml plus any adapter-relative files it references, then load it."""
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "adapter.yaml").write_text(yaml_text)
    for rel, content in (extra_files or {}).items():
        path = adapter_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return load_adapter(adapter_dir)


def make_base_adapter(tmp_path: Path) -> Adapter:
    return make_adapter(tmp_path / "base", BASE_YAML, BASE_EXTRA_FILES)


def original_alpha_skill_md() -> str:
    return (FIXTURE_ROOT / "skills" / "alpha" / "SKILL.md").read_text()


def original_beta_skill_md() -> str:
    return (FIXTURE_ROOT / "skills" / "nested" / "beta" / "SKILL.md").read_text()


def patched_alpha_skill_md() -> str:
    return original_alpha_skill_md().replace("docs/plans/", "kb/acme-skills/exec-plans/")


def test_patch_touched_paths_parses_diff_git_headers() -> None:
    touched = engine.patch_touched_paths(ALPHA_KB_PATHS_PATCH)

    assert touched == {"skills/alpha/SKILL.md"}


def test_patch_touched_paths_returns_both_sides_when_they_differ() -> None:
    text = "diff --git a/old/path.md b/new/path.md\n--- a/old/path.md\n+++ b/new/path.md\n"

    touched = engine.patch_touched_paths(text)

    assert touched == {"old/path.md", "new/path.md"}


def test_validate_patch_targets_allows_patch_touching_unmapped_path(
    tmp_path: Path,
) -> None:
    """A patch touching a path outside every `skills` dir is not a
    canonical-order contradiction (nothing to exclude or override there)."""
    yaml_text = """\
name: demo
source:
  repo: acme/skills
  commit: 0123456789abcdef0123456789abcdef01234567
  annotation: v1.0.0
skills:
  skills/alpha: alpha
patches:
  - patches/touch-unmapped.patch
"""
    unmapped_patch = "\n".join([
        "diff --git a/README.md b/README.md",
        "index 0000000..1111111 100644",
        "--- a/README.md",
        "+++ b/README.md",
        "@@ -1 +1 @@",
        "-old",
        "+new",
        "",
    ])
    adapter = make_adapter(
        tmp_path, yaml_text, {"patches/touch-unmapped.patch": unmapped_patch}
    )

    engine.validate_patch_targets(adapter)  # does not raise


def test_appends_targeting_unstaged_skill_raises(tmp_path: Path) -> None:
    yaml_text = """\
name: demo
source:
  repo: acme/skills
  commit: 0123456789abcdef0123456789abcdef01234567
  annotation: v1.0.0
skills:
  skills/alpha: alpha
appends:
  ghost:
    - appends/block.md
"""
    adapter = make_adapter(
        tmp_path, yaml_text, {"appends/block.md": "## Extra\n"}
    )
    staging = tmp_path / "staging"

    with pytest.raises(AdapterError, match=re.escape("ghost/SKILL.md")):
        engine.build_staging(adapter, FIXTURE_ROOT, staging)


def test_build_staging_applies_patch_and_maps_skills(tmp_path: Path) -> None:
    adapter = make_base_adapter(tmp_path)
    staging = tmp_path / "staging"

    engine.build_staging(adapter, FIXTURE_ROOT, staging)

    alpha_content = (staging / "alpha" / "SKILL.md").read_text()
    assert "kb/acme-skills/exec-plans/<name>.md" in alpha_content
    assert "docs/plans/" not in alpha_content
    assert (staging / "beta" / "SKILL.md").read_text() == original_beta_skill_md()


def test_excluded_file_absent_from_staging(tmp_path: Path) -> None:
    adapter = make_base_adapter(tmp_path)
    staging = tmp_path / "staging"

    engine.build_staging(adapter, FIXTURE_ROOT, staging)

    assert not (staging / "alpha" / "scratch.md").exists()


def test_append_block_present_separated_by_one_blank_line(tmp_path: Path) -> None:
    adapter = make_base_adapter(tmp_path)
    staging = tmp_path / "staging"

    engine.build_staging(adapter, FIXTURE_ROOT, staging)

    content = (staging / "alpha" / "SKILL.md").read_text()
    expected = patched_alpha_skill_md().rstrip() + "\n\n" + APPEND_BLOCK.rstrip() + "\n"
    assert content == expected


def test_override_replaces_installed_file(tmp_path: Path) -> None:
    adapter = make_base_adapter(tmp_path)
    staging = tmp_path / "staging"

    engine.build_staging(adapter, FIXTURE_ROOT, staging)

    assert (staging / "beta" / "references" / "template.md").read_text() == OVERRIDE_TEMPLATE


def test_files_entry_lands_at_staging_root(tmp_path: Path) -> None:
    adapter = make_base_adapter(tmp_path)
    staging = tmp_path / "staging"

    engine.build_staging(adapter, FIXTURE_ROOT, staging)

    assert (staging / "ATTRIBUTION.md").read_text() == ATTRIBUTION


def test_stale_patch_raises_naming_patch_and_rebase_pointer(tmp_path: Path) -> None:
    extra = dict(BASE_EXTRA_FILES)
    extra["patches/alpha-kb-paths.patch"] = STALE_ALPHA_PATCH
    adapter = make_adapter(tmp_path / "stale", BASE_YAML, extra)
    staging = tmp_path / "staging"

    with pytest.raises(
        AdapterError, match=re.escape("patches/alpha-kb-paths.patch")
    ):
        engine.build_staging(adapter, FIXTURE_ROOT, staging)
    with pytest.raises(AdapterError, match="rebase this adapter"):
        engine.build_staging(adapter, FIXTURE_ROOT, staging)


def test_validate_patch_targets_rejects_patch_touching_excluded_path(
    tmp_path: Path,
) -> None:
    yaml_text = """\
name: demo
source:
  repo: acme/skills
  commit: 0123456789abcdef0123456789abcdef01234567
  annotation: v1.0.0
skills:
  skills/alpha: alpha
patches:
  - patches/touch-excluded.patch
excludes:
  - skills/alpha/scratch.md
"""
    adapter = make_adapter(
        tmp_path,
        yaml_text,
        {"patches/touch-excluded.patch": TOUCH_EXCLUDED_PATCH},
    )

    with pytest.raises(AdapterError, match="excluded"):
        engine.validate_patch_targets(adapter)


def test_validate_patch_targets_rejects_patch_touching_overridden_path(
    tmp_path: Path,
) -> None:
    yaml_text = """\
name: demo
source:
  repo: acme/skills
  commit: 0123456789abcdef0123456789abcdef01234567
  annotation: v1.0.0
skills:
  skills/nested/beta: beta
patches:
  - patches/touch-overridden.patch
overrides:
  beta/references/template.md: overrides/template.md
"""
    adapter = make_adapter(
        tmp_path,
        yaml_text,
        {
            "patches/touch-overridden.patch": TOUCH_OVERRIDDEN_PATCH,
            "overrides/template.md": OVERRIDE_TEMPLATE,
        },
    )

    with pytest.raises(AdapterError, match="overridden"):
        engine.validate_patch_targets(adapter)


def test_build_staging_fails_before_any_work_on_target_contradiction(
    tmp_path: Path,
) -> None:
    yaml_text = """\
name: demo
source:
  repo: acme/skills
  commit: 0123456789abcdef0123456789abcdef01234567
  annotation: v1.0.0
skills:
  skills/alpha: alpha
patches:
  - patches/touch-excluded.patch
excludes:
  - skills/alpha/scratch.md
"""
    adapter = make_adapter(
        tmp_path,
        yaml_text,
        {"patches/touch-excluded.patch": TOUCH_EXCLUDED_PATCH},
    )
    staging = tmp_path / "staging"

    with pytest.raises(AdapterError, match="excluded"):
        engine.build_staging(adapter, FIXTURE_ROOT, staging)
    assert not staging.exists()


def test_returned_hash_map_covers_exactly_the_staged_files(tmp_path: Path) -> None:
    adapter = make_base_adapter(tmp_path)
    staging = tmp_path / "staging"

    hashes = engine.build_staging(adapter, FIXTURE_ROOT, staging)

    on_disk = {
        p.relative_to(staging).as_posix(): sha256_file(p)
        for p in staging.rglob("*")
        if p.is_file()
    }
    assert hashes == on_disk
    assert hashes  # non-empty sanity check


def test_build_staging_is_deterministic(tmp_path: Path) -> None:
    adapter = make_base_adapter(tmp_path)
    staging_1 = tmp_path / "staging-1"
    staging_2 = tmp_path / "staging-2"

    hashes_1 = engine.build_staging(adapter, FIXTURE_ROOT, staging_1)
    hashes_2 = engine.build_staging(adapter, FIXTURE_ROOT, staging_2)

    assert hashes_1 == hashes_2


def test_excludes_missing_upstream_file_raises(tmp_path: Path) -> None:
    yaml_text = """\
name: demo
source:
  repo: acme/skills
  commit: 0123456789abcdef0123456789abcdef01234567
  annotation: v1.0.0
skills:
  skills/alpha: alpha
excludes:
  - skills/alpha/does-not-exist.md
"""
    adapter = make_adapter(tmp_path, yaml_text)
    staging = tmp_path / "staging"

    with pytest.raises(
        AdapterError, match=re.escape("skills/alpha/does-not-exist.md")
    ):
        engine.build_staging(adapter, FIXTURE_ROOT, staging)


def test_skills_missing_upstream_dir_raises(tmp_path: Path) -> None:
    yaml_text = """\
name: demo
source:
  repo: acme/skills
  commit: 0123456789abcdef0123456789abcdef01234567
  annotation: v1.0.0
skills:
  skills/nonexistent: gamma
"""
    adapter = make_adapter(tmp_path, yaml_text)
    staging = tmp_path / "staging"

    with pytest.raises(AdapterError, match=re.escape("skills/nonexistent")):
        engine.build_staging(adapter, FIXTURE_ROOT, staging)
