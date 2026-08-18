"""Skill-set adapter definitions: declarative shape and boundary validation.

An adapter is a directory containing `adapter.yaml` plus optional
adapter-local files (patches, append blocks, override/attribution files).
`load_adapter` is the only place adapter shape is checked — everything
downstream trusts the typed `Adapter` object (golden principle 1: validate
at boundaries; golden principle 3: no YOLO dict probing past this module).

Canonical `adapter.yaml` shape (all fields except `patches`/`appends`/
`excludes`/`overrides`/`files`/`wiring` are required; those default empty)::

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

`source.commit` must be the pinned 40-hex commit SHA — tags are never valid
pins (they can move, breaking the byte-identical install guarantee). Every
adapter-relative path referenced by `patches`, `appends`, `overrides`, or
`files` must exist under the adapter directory at load time; `excludes` is a
list of upstream-relative paths (checked against the pinned upstream tree by
later, fetching-aware tasks, not here). `wiring` accepts shorthand
(`spec: [alpha]`) or expanded (`prd: {skills: [alpha], optional: true}`)
form; either way each entry's `skills` list must be non-empty.

This module only parses and validates the declared shape. Fetching the
pinned upstream tree, applying patches, and the `rcorn skills` CLI are later
tasks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

_TOP_LEVEL_KEYS = frozenset({
    "name", "source", "skills", "patches", "appends",
    "excludes", "overrides", "files", "wiring",
})
_SOURCE_KEYS = frozenset({"repo", "commit", "annotation"})
_WIRING_ENTRY_KEYS = frozenset({"skills", "optional"})


class AdapterError(Exception):
    """Agent-readable adapter failure (message carries what/where/fix)."""


@dataclass(frozen=True)
class AdapterSource:
    repo: str        # "owner/name"
    commit: str      # 40-hex sha (the pin)
    annotation: str  # human label, e.g. "v5.0.6" — never used for fetching


@dataclass(frozen=True)
class WiringEntry:
    skills: tuple[str, ...]
    optional: bool = False


@dataclass(frozen=True)
class Adapter:
    name: str
    source: AdapterSource
    skills: dict[str, str]              # upstream dir path -> installed skill name
    patches: tuple[str, ...]            # adapter-relative *.patch, listed order
    appends: dict[str, tuple[str, ...]] # installed name -> adapter-relative .md blocks
    excludes: tuple[str, ...]           # upstream-relative file paths to drop
    overrides: dict[str, str]           # installed-relative path -> adapter-relative file
    files: dict[str, str]               # installed-relative path -> adapter-relative file
    wiring: dict[str, WiringEntry]
    root: Path                          # adapter dir, resolves the relative paths above


def load_adapter(adapter_dir: Path) -> Adapter:
    """Read and validate `adapter_dir / "adapter.yaml"`.

    The only place adapter shape is checked. Raises `AdapterError` naming
    what went wrong, where, and how to fix it (golden principle 4) for any
    malformed field or missing adapter-relative reference.
    """
    adapter_file = adapter_dir / "adapter.yaml"
    if not adapter_file.is_file():
        raise AdapterError(
            f"Adapter at {adapter_dir}: no adapter.yaml found.\n"
            f"  How to fix: create {adapter_file} (see reinicorn.skillset.adapter "
            f"module docstring for the shape)."
        )

    try:
        raw = yaml.safe_load(adapter_file.read_text())
    except yaml.YAMLError as exc:
        raise AdapterError(
            f"Adapter at {adapter_dir}: {adapter_file} is not valid YAML ({exc}).\n"
            f"  How to fix: fix the YAML syntax in {adapter_file}."
        ) from exc

    if not isinstance(raw, dict):
        raise AdapterError(
            f"Adapter at {adapter_dir}: {adapter_file} must be a mapping at the "
            f"top level, got {type(raw).__name__}.\n"
            f"  How to fix: define name/source/skills/... keys at the top of "
            f"{adapter_file}."
        )

    unknown = set(raw) - _TOP_LEVEL_KEYS
    if unknown:
        raise AdapterError(
            f"Adapter at {adapter_dir}: unknown top-level key(s) "
            f"{sorted(unknown)} in {adapter_file}.\n"
            f"  How to fix: remove them, or rename to one of "
            f"{sorted(_TOP_LEVEL_KEYS)}."
        )

    name = _require_name(raw, adapter_dir)
    source = _parse_source(raw.get("source"), name, adapter_dir)
    skills = _parse_skills(raw.get("skills"), name, adapter_dir)
    patches = _parse_patches(raw.get("patches"), name, adapter_dir)
    appends = _parse_appends(raw.get("appends"), name, adapter_dir)
    excludes = _parse_excludes(raw.get("excludes"), name, adapter_dir)
    overrides = _parse_overrides(raw.get("overrides"), name, adapter_dir)
    files = _parse_files(raw.get("files"), name, adapter_dir)
    wiring = _parse_wiring(raw.get("wiring"), name, adapter_dir)

    return Adapter(
        name=name,
        source=source,
        skills=skills,
        patches=patches,
        appends=appends,
        excludes=excludes,
        overrides=overrides,
        files=files,
        wiring=wiring,
        root=adapter_dir,
    )


def _require_name(raw: dict[str, Any], adapter_dir: Path) -> str:
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise AdapterError(
            f"Adapter at {adapter_dir}: missing required top-level key 'name'.\n"
            f"  How to fix: add 'name: <adapter-name>' to "
            f"{adapter_dir / 'adapter.yaml'}."
        )
    return name


def _parse_source(value: Any, name: str, adapter_dir: Path) -> AdapterSource:
    if not isinstance(value, dict):
        raise AdapterError(
            f"Adapter '{name}' at {adapter_dir}: missing or invalid 'source' block.\n"
            f"  How to fix: add a 'source: {{repo, commit, annotation}}' block to "
            f"adapter.yaml."
        )

    unknown = set(value) - _SOURCE_KEYS
    if unknown:
        raise AdapterError(
            f"Adapter '{name}' at {adapter_dir}: unknown key(s) {sorted(unknown)} "
            f"under 'source'.\n"
            f"  How to fix: remove them, or rename to one of {sorted(_SOURCE_KEYS)}."
        )

    repo = value.get("repo")
    if not isinstance(repo, str) or not _REPO_RE.match(repo):
        raise AdapterError(
            f"Adapter '{name}' at {adapter_dir}: source.repo {repo!r} must look "
            f"like 'owner/name'.\n"
            f"  How to fix: set source.repo to the upstream GitHub 'owner/repo' slug."
        )

    commit = value.get("commit")
    if not isinstance(commit, str) or not _COMMIT_RE.match(commit):
        raise AdapterError(
            f"Adapter '{name}' at {adapter_dir}: source.commit '{commit}' is not a "
            f"40-hex commit SHA.\n  Tags are not valid pins — resolve the tag to its "
            f"commit and pin that (see spec: skill-base-agnostic adapter source rules)."
        )

    annotation = value.get("annotation")
    if not isinstance(annotation, str) or not annotation:
        raise AdapterError(
            f"Adapter '{name}' at {adapter_dir}: missing required 'source.annotation'.\n"
            f"  How to fix: add a human-readable label, e.g. 'annotation: v1.0.0' "
            f"(never used for fetching, so it may safely be a tag name)."
        )

    return AdapterSource(repo=repo, commit=commit, annotation=annotation)


def _parse_skills(value: Any, name: str, adapter_dir: Path) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise AdapterError(
            f"Adapter '{name}' at {adapter_dir}: 'skills' must be a non-empty "
            f"mapping of upstream path -> installed skill name.\n"
            f"  How to fix: list at least one 'skills: {{<upstream-path>: "
            f"<installed-name>}}' entry — there is no 'take everything' mode."
        )

    for upstream, installed in value.items():
        # Check upstream key (gap 2: emptiness).
        if not isinstance(upstream, str):
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: invalid 'skills' entry "
                f"{upstream!r}: {installed!r}.\n"
                f"  How to fix: use 'skills: {{<upstream-path>: <installed-name>}}' "
                f"with non-empty string keys and values."
            )
        if not upstream:
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: 'skills' key is empty.\n"
                f"  How to fix: use 'skills: {{<upstream-path>: <installed-name>}}' "
                f"with non-empty upstream paths."
            )

        # Check installed value (gap 1b: single component, no escape).
        if not isinstance(installed, str) or not installed:
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: invalid 'skills' entry "
                f"{upstream!r}: {installed!r}.\n"
                f"  How to fix: use 'skills: {{<upstream-path>: <installed-name>}}' "
                f"with non-empty string keys and values."
            )
        if Path(installed).is_absolute():
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: 'skills' value {installed!r} "
                f"is an absolute path.\n"
                f"  How to fix: use a single skill name component, not an absolute path."
            )
        if "/" in installed or ".." in Path(installed).parts:
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: 'skills' value {installed!r} "
                f"must be a single non-empty path component.\n"
                f"  How to fix: use just the skill name, no '/' or '..' separators "
                f"(e.g., 'alpha', not 'nested/alpha' or '../escape')."
            )

    return dict(value)


def _parse_patches(value: Any, name: str, adapter_dir: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
        raise AdapterError(
            f"Adapter '{name}' at {adapter_dir}: 'patches' must be a list of "
            f"adapter-relative *.patch file paths.\n"
            f"  How to fix: list patch files, in application order, under "
            f"'patches:'."
        )
    for rel in value:
        _require_adapter_file(rel, "patches", name, adapter_dir)
    return tuple(value)


def _parse_appends(
    value: Any, name: str, adapter_dir: Path
) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AdapterError(
            f"Adapter '{name}' at {adapter_dir}: 'appends' must be a mapping of "
            f"installed skill name -> list of adapter-relative append blocks.\n"
            f"  How to fix: use 'appends: {{<skill-name>: [<block.md>, ...]}}'."
        )

    result: dict[str, tuple[str, ...]] = {}
    for skill_name, blocks in value.items():
        if (
            not isinstance(skill_name, str)
            or not isinstance(blocks, list)
            or not blocks
            or not all(isinstance(b, str) for b in blocks)
        ):
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: 'appends.{skill_name}' must be "
                f"a non-empty list of adapter-relative file paths.\n"
                f"  How to fix: use 'appends: {{{skill_name}: [<block.md>, ...]}}'."
            )
        for rel in blocks:
            _require_adapter_file(rel, f"appends.{skill_name}", name, adapter_dir)
        result[skill_name] = tuple(blocks)

    return result


def _parse_excludes(value: Any, name: str, adapter_dir: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
        raise AdapterError(
            f"Adapter '{name}' at {adapter_dir}: 'excludes' must be a list of "
            f"upstream-relative file paths.\n"
            f"  How to fix: list the upstream paths to drop under 'excludes:'."
        )
    return tuple(value)


def _parse_overrides(value: Any, name: str, adapter_dir: Path) -> dict[str, str]:
    return _parse_installed_path_mapping(value, "overrides", name, adapter_dir)


def _parse_files(value: Any, name: str, adapter_dir: Path) -> dict[str, str]:
    return _parse_installed_path_mapping(value, "files", name, adapter_dir)


def _parse_installed_path_mapping(
    value: Any, field: str, name: str, adapter_dir: Path
) -> dict[str, str]:
    """Shared shape for 'overrides' and 'files': installed path -> adapter file."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AdapterError(
            f"Adapter '{name}' at {adapter_dir}: '{field}' must be a mapping of "
            f"installed-relative path -> adapter-relative file.\n"
            f"  How to fix: use '{field}: {{<installed-path>: <adapter-file>}}'."
        )

    for installed_path, rel in value.items():
        if not isinstance(installed_path, str) or not isinstance(rel, str):
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: invalid '{field}' entry "
                f"{installed_path!r}: {rel!r}.\n"
                f"  How to fix: use a string installed-relative path and a string "
                f"adapter-relative file."
            )
        # Validate that installed-relative destination paths are safe (no escape).
        if Path(installed_path).is_absolute():
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: '{field}' key '{installed_path}' "
                f"is an absolute path.\n"
                f"  How to fix: use an installed-relative path with no leading '/'."
            )
        if ".." in Path(installed_path).parts:
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: '{field}' key '{installed_path}' "
                f"escapes the installed directory.\n"
                f"  How to fix: use an installed-relative path with no '..' components."
            )
        _require_adapter_file(rel, field, name, adapter_dir)

    return dict(value)


def _parse_wiring(value: Any, name: str, adapter_dir: Path) -> dict[str, WiringEntry]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AdapterError(
            f"Adapter '{name}' at {adapter_dir}: 'wiring' must be a mapping of "
            f"doc-type -> skill list (shorthand) or {{skills, optional}} (expanded).\n"
            f"  How to fix: use 'wiring: {{<doc-type>: [<skill>, ...]}}' or the "
            f"expanded form."
        )

    result: dict[str, WiringEntry] = {}
    for doc_type, entry in value.items():
        skills, optional = _parse_wiring_entry(entry, doc_type, name, adapter_dir)
        # Gap 3: split error message for empty list vs non-string elements.
        if not skills:
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: 'wiring.{doc_type}.skills' "
                f"must be a non-empty list.\n"
                f"  How to fix: list at least one skill under 'wiring.{doc_type}'."
            )
        # Check for non-string elements.
        non_strings = [s for s in skills if not isinstance(s, str)]
        if non_strings:
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: 'wiring.{doc_type}.skills' "
                f"entries must be strings, got {non_strings!r}.\n"
                f"  How to fix: ensure all entries under 'wiring.{doc_type}' are "
                f"skill name strings."
            )
        result[doc_type] = WiringEntry(skills=tuple(skills), optional=optional)

    return result


def _parse_wiring_entry(
    entry: Any, doc_type: str, name: str, adapter_dir: Path
) -> tuple[list[Any], bool]:
    """One `wiring` value: shorthand list, or expanded {skills, optional} mapping."""
    if isinstance(entry, list):
        return entry, False

    if isinstance(entry, dict):
        unknown = set(entry) - _WIRING_ENTRY_KEYS
        if unknown:
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: unknown key(s) "
                f"{sorted(unknown)} under 'wiring.{doc_type}'.\n"
                f"  How to fix: use only 'skills' and 'optional'."
            )
        optional = entry.get("optional", False)
        if not isinstance(optional, bool):
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: 'wiring.{doc_type}.optional' "
                f"must be true or false.\n"
                f"  How to fix: set 'optional: true' or 'optional: false', or "
                f"omit it."
            )
        skills = entry.get("skills")
        if not isinstance(skills, list):
            raise AdapterError(
                f"Adapter '{name}' at {adapter_dir}: 'wiring.{doc_type}.skills' "
                f"must be a non-empty list of skill names.\n"
                f"  How to fix: list at least one skill under 'wiring.{doc_type}'."
            )
        return skills, optional

    raise AdapterError(
        f"Adapter '{name}' at {adapter_dir}: 'wiring.{doc_type}' must be a list "
        f"of skill names or a {{skills, optional}} mapping.\n"
        f"  How to fix: use 'wiring: {{{doc_type}: [<skill>, ...]}}'."
    )


def _require_adapter_file(rel: str, field: str, name: str, adapter_dir: Path) -> None:
    """Path-safety plus existence check for one adapter-relative reference."""
    _check_path_safe(rel, field, name, adapter_dir)
    full = adapter_dir / rel
    if not full.is_file():
        raise AdapterError(
            f"Adapter '{name}' at {adapter_dir}: {field} references missing file "
            f"'{rel}'.\n"
            f"  How to fix: create {full}, or fix the path in adapter.yaml."
        )


def _check_path_safe(rel: str, field: str, name: str, adapter_dir: Path) -> None:
    """Refuse absolute paths and '..' components — never escape the adapter dir."""
    if Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise AdapterError(
            f"Adapter '{name}' at {adapter_dir}: {field} path '{rel}' escapes the "
            f"adapter directory.\n"
            f"  How to fix: use an adapter-relative path with no '..' components "
            f"and no leading '/'."
        )
