"""Centralized doc-type registry: built-in defaults plus a kb-side overlay.

Single source of truth for all kb document type metadata: paths, filename
patterns, protection flags, linter sections, index files, and per-type
frontmatter vocabulary. `REGISTRY` holds the built-in defaults; the
effective registry — defaults overlaid by an optional
``kb/<scope>/doc-types.yaml`` — comes from `registry()` and is what every
consumer reads (spec: process-as-config-doc-type-registry-overlay).

Adding a behavior to the engine:

1. Add the field to `DocType` with an off-by-default value (or a new enum
   member), so every existing row is unaffected, and its composition
   invariant to `_validate_rows()`.
2. For each event that reacts: one function or rule reading `dt.<field>`,
   appended to that event's explicit list (and enabled in the seeded
   ``linters/.lint-config.json`` for a lint rule).
3. Extend the phantom-type test: a synthetic row with the behavior on
   asserts each event fires; the defaults assert nothing changed.
4. Document the field in the spec that introduces it; `doc-types show`
   and the overlay accept it without further work.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

OVERLAY_FILENAME = "doc-types.yaml"


class DocTypesError(ValueError):
    """A broken registry overlay. Fails closed: no silent fallback to defaults."""


class Addressing(Enum):
    """How a doc of this type is identified and pathed."""

    SLUG = "slug"
    BRANCH = "branch"
    SINGLETON = "singleton"


class TitleSource(Enum):
    """Where a new doc's title comes from at creation time."""

    TITLE = "title"
    FREE_TEXT = "free_text"
    NONE = "none"


class CreateMode(Enum):
    """Whether creation writes a new file or appends to the singleton."""

    FILE = "file"
    APPEND = "append"


@dataclass(frozen=True)
class DependsOn:
    """This type's docs must reference an approved doc of another type.

    The doc's `field:` frontmatter must resolve to a tracked doc of `type`
    with `status`, or be the N/A sentinel. Read by the `kb/draft-refs` lint
    and the pre-push dependency gate (refs.py).
    """

    field: str
    type: str
    status: str


@dataclass(frozen=True)
class Closes:
    """This type is the closer of another (e.g. retro closes plan).

    Implies: the closer is created inside the closee's dir and `<closee>
    complete` moves the stage dir with both docs. When `required`,
    `complete` refuses without a filled closer (`--abandon` is the escape)
    and the `kb/closer-filled` lint reports the gap; otherwise a missing
    closer only warns.
    """

    type: str
    required: bool = False


@dataclass(frozen=True)
class DocType:
    """Metadata for a single kb document type."""

    key: str
    dir_path: str  # Relative to repo-scoped dir (e.g. "specs")
    filename: str  # Pattern: "{slug}.md", "active/{branch}/plan.md", etc.
    protected: bool  # Whether direct kb edits are blocked
    help_text: str  # CLI group help, wired into cli.py's generated subparser
    # Creation body appended after the frontmatter + H1. File-mode bodies may
    # name {title} {author} {date} {sections} {text}; append-mode bodies
    # (CreateMode.APPEND) are formatted with {num} and {title} only.
    template_body: str
    addressing: Addressing
    title_source: TitleSource = TitleSource.TITLE
    create_verb: str = "create"
    create_mode: CreateMode = CreateMode.FILE
    create_status: str = "draft"  # frontmatter `status:` a new doc opens with
    # Static per-type frontmatter, as (key, value) pairs (frozen-friendly).
    extra_meta: tuple[tuple[str, str], ...] = ()
    readme_label: str | None = None  # Seeded kb README row; None = no row
    index_file: str | None = None  # For freshness linter
    required_sections: tuple[str, ...] = ()  # Linter checks these headers
    gated: bool = False  # Review-gated: create writes to drafts/, approval via the review lane
    # Per-type frontmatter vocabulary (beyond the core fields every doc
    # carries). `branch` is auto-added to both for branch-addressed rows;
    # `id` is auto-added to `fields` for rows with a {seq} filename.
    fields: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    # Declarative relations (spec: process-as-config §2). None = behavior off.
    depends_on: DependsOn | None = None
    closes: Closes | None = None

    @property
    def create_hint(self) -> str:
        """Exact CLI command that creates docs of this type.

        Derived from `create_verb`/`title_source`, not a hand-maintained
        literal — a per-row literal here and `skillset.wiring`'s own
        derivation used to encode the same fact twice and had drifted apart
        (`"<idea>"` vs `"<text>"`). This is the single source; `wiring`
        wraps it in markdown code quotes for the wiring doc's table cell.
        """
        if self.title_source is TitleSource.TITLE:
            return f'rcorn {self.key} {self.create_verb} "<title>"'
        if self.title_source is TitleSource.FREE_TEXT:
            return f'rcorn {self.key} {self.create_verb} "<text>"'
        return f"rcorn {self.key} {self.create_verb}"


# Row order is meaningful: CLI groups render in registry order, and
# by_dir() prefers earlier rows when two types share a dir_path
# (plan and retro both use "exec-plans" — plan must stay first).
REGISTRY: dict[str, DocType] = {
    "spec": DocType(
        key="spec",
        dir_path="specs",
        filename="{slug}.md",
        protected=True,
        help_text="Spec doc operations (the implementation contract)",
        template_body=(
            "\n## Problem\n\n_Describe the problem._\n"
            "\n## Design Goals\n\n_What must be true when this is done._\n"
            "\n## Design\n\n_How it works._\n"
            "\n## Non-Goals\n\n_What this explicitly does not cover._\n"
        ),
        addressing=Addressing.SLUG,
        readme_label="Approved specs",
        index_file="index.md",
        required_sections=("Problem", "Design Goals", "Design", "Non-Goals"),
        gated=True,
        fields=("supersedes", "superseded_by", "implemented_by"),
    ),
    "prd": DocType(
        key="prd",
        dir_path="prds",
        filename="{slug}.md",
        protected=True,
        help_text="Product requirements doc operations",
        template_body=(
            "\n## Overview\n\n_One-paragraph summary._\n"
            "\n## User Stories\n\n- As a [role], I want [goal] so that [benefit].\n"
            "\n## Acceptance Criteria\n\n- [ ] _Criterion 1_\n"
            "\n## Out of Scope\n\n_What this PRD explicitly does not cover._\n"
            "\n## Open Questions\n\n_Unresolved decisions._\n"
        ),
        addressing=Addressing.SLUG,
        readme_label="Product requirements",
        index_file="index.md",
        required_sections=(
            "Overview",
            "User Stories",
            "Acceptance Criteria",
            "Out of Scope",
            "Open Questions",
        ),
        fields=("supersedes", "superseded_by", "implemented_by"),
    ),
    "debt": DocType(
        key="debt",
        dir_path="tech-debt",
        filename="{slug}.md",
        protected=True,
        help_text="Tech debt doc operations",
        template_body=(
            "\n## Impact\n\n_What this debt causes._\n"
            "\n## Remediation Plan\n\n_How to fix it._\n"
        ),
        addressing=Addressing.SLUG,
        extra_meta=(
            ("severity", "medium"),
            ("category", "_domain_"),
            ("remediation", "planned"),
        ),
        readme_label="Technical debt",
        index_file="index.md",
        required_sections=("Impact", "Remediation Plan"),
        fields=("id", "category", "severity", "remediation"),
    ),
    "idea": DocType(
        key="idea",
        dir_path="ideas",
        filename="{username}/{slug}.md",
        protected=True,
        help_text="Idea capture",
        template_body=(
            "\n## Description\n\n{text}\n"
            "\n## Notes\n\n_No additional notes yet._\n"
        ),
        addressing=Addressing.SLUG,
        title_source=TitleSource.FREE_TEXT,
        create_status="new",
        fields=("promoted_to",),
    ),
    "plan": DocType(
        key="plan",
        dir_path="exec-plans",
        filename="{stage}/{branch}/plan.md",
        protected=True,
        help_text="Execution plan operations",
        template_body="",  # fallback plan.md is frontmatter + H1 only
        addressing=Addressing.BRANCH,
        title_source=TitleSource.NONE,
        create_status="planning",
        readme_label="Active plans",
        required_sections=("Goal", "Acceptance Criteria", "Tasks"),
        fields=("branch", "ticket", "spec", "retro"),
        required_fields=("branch",),
        depends_on=DependsOn(field="spec", type="spec", status="approved"),
    ),
    "retro": DocType(
        key="retro",
        dir_path="exec-plans",
        filename="retro.md",
        protected=True,
        help_text="Retrospective operations",
        template_body="{sections}",
        addressing=Addressing.BRANCH,
        title_source=TitleSource.NONE,
        required_sections=(
            "What Went Well",
            "What Could Be Improved",
            "Lessons Learned",
            "Action Items",
        ),
        fields=("branch", "plan"),
        required_fields=("branch",),
        closes=Closes(type="plan", required=False),
    ),
    "principle": DocType(
        key="principle",
        dir_path=".",
        filename="golden-principles.md",
        protected=False,
        help_text="Golden principle operations",
        template_body=(
            "\n\n{num}. **{title}**\n"
            "   - _Rule description_\n"
            "   - Prevents: _What this rule prevents_\n"
        ),
        addressing=Addressing.SINGLETON,
        create_verb="add",
        create_mode=CreateMode.APPEND,
        create_status="active",
        readme_label="Golden principles",
    ),
}


# --- Overlay loading -------------------------------------------------------

_ENUM_FIELDS: dict[str, type[Enum]] = {
    "addressing": Addressing,
    "title_source": TitleSource,
    "create_mode": CreateMode,
}
# Overlay row keys derive from the dataclass by field name — there is no
# second schema to keep in sync. `key` comes from the mapping key and
# `disabled` is the removal marker, not a field.
_ROW_KEYS = frozenset(f.name for f in dataclasses.fields(DocType)) - {"key"}
_ADD_MANDATORY = ("dir_path", "filename", "addressing")

_PLACEHOLDER_RE = re.compile(r"\{(\w+)(?::[^}]*)?\}")
# Placeholders each addressing mode may (and must) use in `filename`.
_ALLOWED_PLACEHOLDERS = {
    Addressing.SLUG: frozenset({"slug", "username", "seq"}),
    Addressing.BRANCH: frozenset({"branch", "stage"}),
    Addressing.SINGLETON: frozenset(),
}
_IDENTITY_PLACEHOLDER = {Addressing.SLUG: "slug", Addressing.BRANCH: "branch"}
# Relation values in the overlay are mappings coerced into these dataclasses.
_RELATION_FIELDS: dict[str, type] = {"depends_on": DependsOn, "closes": Closes}


def filename_placeholders(dt: DocType) -> frozenset[str]:
    """Placeholder names used in the row's filename pattern."""
    return frozenset(_PLACEHOLDER_RE.findall(dt.filename))


_PLACEHOLDER_FULL_RE = re.compile(r"\{(\w+)(?::[^}]*)?\}")


def filename_regex(filename: str) -> re.Pattern[str]:
    """The filename pattern's own regex: {seq} captures digits, every other
    placeholder matches one path segment."""
    out: list[str] = []
    pos = 0
    for m in _PLACEHOLDER_FULL_RE.finditer(filename):
        out.append(re.escape(filename[pos:m.start()]))
        out.append(r"(?P<seq>\d+)" if m.group(1) == "seq" else r"[^/]+")
        pos = m.end()
    out.append(re.escape(filename[pos:]))
    return re.compile("".join(out))


def seq_display_id(filename: str, seq: int) -> str:
    """The display id a {seq} filename stamps into the doc's `id` field:
    the pattern's seq-bearing basename prefix, formatted
    ("RFC-{seq:04}-{slug}.md" at 7 → "RFC-0007")."""
    for m in _PLACEHOLDER_FULL_RE.finditer(filename):
        if m.group(1) == "seq":
            prefix = filename[: m.end()].rsplit("/", 1)[-1]
            return prefix.format(seq=seq)
    raise ValueError(f"no {{seq}} placeholder in '{filename}'")


def _coerce(source: str, key: str, name: str, value: Any) -> Any:
    """One overlay value into its dataclass field's type."""

    def bad(expected: str) -> DocTypesError:
        return DocTypesError(
            f"{source}: doc_types.{key}.{name} — expected {expected}, "
            f"got {value!r}"
        )

    if name in _ENUM_FIELDS:
        enum_cls = _ENUM_FIELDS[name]
        try:
            return enum_cls(value)
        except ValueError:
            raise bad(
                f"one of {[m.value for m in enum_cls]}"
            ) from None
    if name in _RELATION_FIELDS:
        if value is None:
            return None  # explicit null clears an inherited relation
        rel_cls = _RELATION_FIELDS[name]
        rel_fields = {f.name for f in dataclasses.fields(rel_cls)}
        rel_required = {
            f.name for f in dataclasses.fields(rel_cls)
            if f.default is dataclasses.MISSING
        }
        if (
            not isinstance(value, dict)
            or not set(value) <= rel_fields
            or not rel_required <= set(value)
        ):
            raise bad(
                f"a mapping with key(s) {sorted(rel_required)} "
                f"(optional: {sorted(rel_fields - rel_required)}) or null"
            )
        for k, v in value.items():
            annotated = rel_cls.__dataclass_fields__[k].type
            expected = bool if annotated == "bool" else str
            if not isinstance(v, expected):
                raise bad(f"{expected.__name__} for '{k}', got {v!r}")
        return rel_cls(**value)
    if name == "extra_meta":
        if not isinstance(value, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        ):
            raise bad("a mapping of string to string")
        return tuple(value.items())
    if name in ("required_sections", "fields", "required_fields"):
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise bad("a list of strings")
        return tuple(value)
    if name in ("readme_label", "index_file"):
        if value is not None and not isinstance(value, str):
            raise bad("a string or null")
        return value
    default = DocType.__dataclass_fields__[name].default
    expected_type = type(default) if default is not dataclasses.MISSING else str
    if not isinstance(value, expected_type):
        raise bad(expected_type.__name__)
    return value


def _row_from_overlay(
    source: str, key: str, base: DocType | None, entry: dict[str, Any],
) -> DocType:
    """Apply one overlay entry: override *base* or build a new row."""
    unknown = set(entry) - _ROW_KEYS
    if unknown:
        raise DocTypesError(
            f"{source}: doc_types.{key} has unknown key(s) "
            f"{sorted(unknown)} — valid keys: {sorted(_ROW_KEYS)}"
        )
    coerced = {
        name: _coerce(source, key, name, value)
        for name, value in entry.items()
    }
    if base is not None:
        return dataclasses.replace(base, **coerced)
    missing = [name for name in _ADD_MANDATORY if name not in coerced]
    if missing:
        raise DocTypesError(
            f"{source}: doc_types.{key} adds a new type but is missing "
            f"mandatory key(s) {missing}"
        )
    # Derived defaults so a minimal added row is usable.
    coerced.setdefault("help_text", f"{key} doc operations")
    coerced.setdefault("template_body", "{sections}")
    coerced.setdefault("protected", True)
    return DocType(key=key, **coerced)


def _auto_fields(dt: DocType) -> DocType:
    """Engine-reserved frontmatter fields the loader adds, never the overlay.

    Branch-addressed rows carry `branch` (its value is the git branch name,
    path-sanitized); rows with a {seq} filename carry the stamped `id`.
    """
    fields = list(dt.fields)
    required = list(dt.required_fields)
    if dt.addressing is Addressing.BRANCH:
        if "branch" not in fields:
            fields.insert(0, "branch")
        if "branch" not in required:
            required.insert(0, "branch")
    if "seq" in filename_placeholders(dt) and "id" not in fields:
        fields.insert(0, "id")
    if fields != list(dt.fields) or required != list(dt.required_fields):
        return dataclasses.replace(
            dt, fields=tuple(fields), required_fields=tuple(required),
        )
    return dt


def _validate_rows(rows: dict[str, DocType], source: str) -> None:
    """Composition invariants over the effective registry, in one place.

    A plain raise, not `assert`: it must fire under `python -O` too, so an
    invalid row can never load. Fails closed with the source and offending
    key — a broken process config must not silently revert to defaults.
    """
    for dt in rows.values():
        where = f"{source}: doc_types.{dt.key}"
        if dt.gated and dt.addressing is not Addressing.SLUG:
            raise DocTypesError(
                f"{where}: gated=True requires addressing 'slug', got "
                f"'{dt.addressing.value}' — the review lane derives "
                "candidate paths from slugs (review.make_target)."
            )
        used = filename_placeholders(dt)
        allowed = _ALLOWED_PLACEHOLDERS[dt.addressing]
        if not used <= allowed:
            raise DocTypesError(
                f"{where}: filename '{dt.filename}' uses placeholder(s) "
                f"{sorted(used - allowed)} not allowed for addressing "
                f"'{dt.addressing.value}' (allowed: {sorted(allowed)})"
            )
        if _PLACEHOLDER_RE.findall(dt.filename).count("seq") > 1:
            # `used` is a set, so a repeated {seq} passes the check above;
            # filename_regex() would then emit two named groups and fail at
            # the first create.
            raise DocTypesError(
                f"{where}: filename '{dt.filename}' repeats '{{seq}}' — one "
                "sequence number per filename"
            )
        identity = _IDENTITY_PLACEHOLDER.get(dt.addressing)
        if (
            identity is not None
            and identity not in used
            and dt.create_mode is not CreateMode.APPEND
            and dt.closes is None  # a closer's path derives from its closee
        ):
            raise DocTypesError(
                f"{where}: filename '{dt.filename}' must contain "
                f"'{{{identity}}}' for addressing '{dt.addressing.value}'"
            )

    _validate_relations(rows, source)


def _validate_relations(rows: dict[str, DocType], source: str) -> None:
    """Relation invariants (spec: process-as-config §1/§2).

    Runs after disabled rows are dropped, so disabling a related group is
    atomic; only an *enabled* row pointing at a missing/disabled target is
    an error.
    """
    closers: dict[str, str] = {}  # closee key -> closer key
    for dt in rows.values():
        where = f"{source}: doc_types.{dt.key}"
        if dt.depends_on is not None:
            rel = dt.depends_on
            if rel.type not in rows:
                raise DocTypesError(
                    f"{where}: depends_on targets '{rel.type}', which is "
                    "not in the effective registry (missing or disabled) — "
                    "clear the relation or disable this row too"
                )
            if rel.field not in dt.fields:
                raise DocTypesError(
                    f"{where}: depends_on.field '{rel.field}' is not a "
                    f"declared field of this row (fields: {list(dt.fields)})"
                )
        if dt.closes is None:
            continue
        target = rows.get(dt.closes.type)
        if target is None:
            raise DocTypesError(
                f"{where}: closes targets '{dt.closes.type}', which is not "
                "in the effective registry (missing or disabled) — clear "
                "the relation or disable this row too"
            )
        if (
            dt.addressing is not Addressing.BRANCH
            or target.addressing is not Addressing.BRANCH
        ):
            raise DocTypesError(
                f"{where}: closes pairs must both be branch-addressed "
                f"('{dt.key}' is '{dt.addressing.value}', "
                f"'{target.key}' is '{target.addressing.value}')"
            )
        if "/" in dt.filename or filename_placeholders(dt):
            raise DocTypesError(
                f"{where}: a closer's filename must be a bare name with no "
                f"placeholders or '/', got '{dt.filename}' — its path "
                "derives from the closee's dir"
            )
        prior = closers.setdefault(dt.closes.type, dt.key)
        if prior != dt.key:
            raise DocTypesError(
                f"{where}: '{dt.closes.type}' already has closer "
                f"'{prior}' — at most one enabled closer per closee"
            )
    for closee_key in closers:
        closee = rows[closee_key]
        if closee.closes is not None:
            raise DocTypesError(
                f"{source}: doc_types.{closee_key}: a closer cannot itself "
                "be closable (closes chains are depth one)"
            )
        if closee.title_source is not TitleSource.NONE:
            # The lifecycle create derives the title from the branch; a
            # title the parser demanded and the command ignored would be a
            # silent lie to the user.
            raise DocTypesError(
                f"{source}: doc_types.{closee_key}: a closable type's title "
                "is derived from the branch — set title_source: none (got "
                f"'{closee.title_source.value}')"
            )
        if not closee.filename.startswith("{stage}/"):
            raise DocTypesError(
                f"{source}: doc_types.{closee_key}: a closable type's "
                "filename must be '{stage}/{branch}/<name>', got "
                f"'{closee.filename}'"
            )


def _apply_overlay(
    defaults: dict[str, DocType], data: Any, source: str,
) -> dict[str, DocType]:
    """Overlay semantics: override listed fields, add rows, drop disabled.

    Disabled rows are dropped before invariant checks, taking their own
    relations with them (relations land in stage 2; the drop-first order is
    the contract that makes disabling a related group atomic).
    """
    if not isinstance(data, dict) or not isinstance(
        data.get("doc_types"), dict
    ):
        raise DocTypesError(
            f"{source}: expected a top-level 'doc_types:' mapping"
        )
    rows = dict(defaults)
    for key, entry in data["doc_types"].items():
        if not isinstance(entry, dict):
            raise DocTypesError(
                f"{source}: doc_types.{key} must be a mapping, "
                f"got {entry!r}"
            )
        entry = dict(entry)
        disabled = entry.pop("disabled", False)
        if not isinstance(disabled, bool):
            # A truthy string like "false" must not silently drop the row.
            raise DocTypesError(
                f"{source}: doc_types.{key}.disabled — expected a boolean, "
                f"got {disabled!r}"
            )
        if disabled:
            if entry:
                raise DocTypesError(
                    f"{source}: doc_types.{key} sets disabled: true — "
                    "no other keys are allowed on a disabled row"
                )
            rows.pop(key, None)
            continue
        rows[key] = _row_from_overlay(source, key, rows.get(key), entry)
    return rows


def overlay_path(root: Path) -> Path:
    """Where this repo's registry overlay lives: the kb scope dir."""
    from reinicorn.config import KB_DIR_NAME, kb_scope

    return root / KB_DIR_NAME / kb_scope(root) / OVERLAY_FILENAME


def _load_overlay_data(path: Path) -> Any:
    import yaml

    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise DocTypesError(f"{path}: not valid YAML — {e}") from None


# Effective registries, resolved once per process per repo root.
_CACHE: dict[str, dict[str, DocType]] = {}


def registry(root: Path | None = None) -> dict[str, DocType]:
    """The effective doc-type registry for *root* (default: this repo).

    Built-in defaults overlaid by ``kb/<scope>/doc-types.yaml`` when one
    exists, validated into the same frozen `DocType` objects every consumer
    already uses. Raises `DocTypesError` on a broken overlay (fail closed).
    """
    cwd_key = None
    if root is None:
        # Keyed by cwd so the repo_root subprocess runs once per process,
        # not once per doc in a lint loop — while a chdir (tests) still
        # resolves the right repo.
        from pathlib import Path as _Path

        cwd_key = "cwd:" + str(_Path.cwd())
        if cwd_key in _CACHE:
            return _CACHE[cwd_key]
        from reinicorn.git import repo_root

        root = repo_root(quiet=True)
    cache_key = str(root) if root is not None else ""
    if cache_key in _CACHE:
        if cwd_key is not None:
            _CACHE[cwd_key] = _CACHE[cache_key]
        return _CACHE[cache_key]

    rows = dict(REGISTRY)
    source = "built-in defaults"
    if root is not None:
        path = overlay_path(root)
        if path.is_file():
            source = str(path)
            rows = _apply_overlay(REGISTRY, _load_overlay_data(path), source)
    rows = {key: _auto_fields(dt) for key, dt in rows.items()}
    _validate_rows(rows, source)
    _CACHE[cache_key] = rows
    if cwd_key is not None:
        _CACHE[cwd_key] = rows
    return rows


def overlay_keys(root: Path | None = None) -> frozenset[str]:
    """Type keys the overlay touches (overrides or adds) — for `doc-types
    show` annotations. Empty when there is no overlay."""
    if root is None:
        from reinicorn.git import repo_root

        root = repo_root(quiet=True)
    if root is None:
        return frozenset()
    path = overlay_path(root)
    if not path.is_file():
        return frozenset()
    data = _load_overlay_data(path)
    if not isinstance(data, dict) or not isinstance(
        data.get("doc_types"), dict
    ):
        return frozenset()
    return frozenset(data["doc_types"])


def overlay_schema() -> dict[str, Any]:
    """JSON Schema for ``doc-types.yaml``, derived from the dataclass.

    For editor validation (`doc-types show --schema`). Field names come
    from `DocType` itself, so adding a field needs no schema edit here.
    """

    def field_schema(name: str) -> dict[str, Any]:
        if name in _ENUM_FIELDS:
            return {"enum": [m.value for m in _ENUM_FIELDS[name]]}
        if name in _RELATION_FIELDS:
            rel_cls = _RELATION_FIELDS[name]
            rel_fields = dataclasses.fields(rel_cls)
            return {
                "type": ["object", "null"],
                "additionalProperties": False,
                "required": [
                    f.name for f in rel_fields
                    if f.default is dataclasses.MISSING
                ],
                "properties": {
                    f.name: {
                        "type": "boolean" if f.type == "bool" else "string"
                    }
                    for f in rel_fields
                },
            }
        if name == "extra_meta":
            return {"type": "object", "additionalProperties": {"type": "string"}}
        if name in ("required_sections", "fields", "required_fields"):
            return {"type": "array", "items": {"type": "string"}}
        if name in ("readme_label", "index_file"):
            return {"type": ["string", "null"]}
        default = DocType.__dataclass_fields__[name].default
        if isinstance(default, bool):
            return {"type": "boolean"}
        return {"type": "string"}

    row = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "disabled": {"type": "boolean"},
            **{name: field_schema(name) for name in sorted(_ROW_KEYS)},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"Reinicorn doc-type registry overlay ({OVERLAY_FILENAME})",
        "type": "object",
        "additionalProperties": False,
        "required": ["doc_types"],
        "properties": {
            "doc_types": {"type": "object", "additionalProperties": row},
        },
    }


def _reset_registry_cache() -> None:
    """Test hook: forget memoized effective registries."""
    _CACHE.clear()


_validate_rows(
    {key: _auto_fields(dt) for key, dt in REGISTRY.items()},
    "built-in defaults",
)


def get_doc_dir(key: str, repo_dir: Path) -> Path:
    """Resolve the full directory path for a doc type within a repo scope dir."""
    return repo_dir / registry()[key].dir_path


def get_protected_map() -> dict[str, str]:
    """Return {dir_path: key} for all protected doc types.

    Excludes entries with dir_path "." (like principle) since they live
    at the repo-scope root and don't have a distinct subdirectory.
    """
    return {
        dt.dir_path: dt.key
        for dt in registry().values()
        if dt.protected and dt.dir_path != "."
    }


def by_dir(dir_name: str) -> DocType | None:
    """Reverse lookup: find a DocType by its directory name."""
    for dt in registry().values():
        if dt.dir_path == dir_name:
            return dt
    return None


DRAFTS_DIR_NAME = "drafts"


def drafts_dir(key: str, repo_dir: Path) -> Path:
    """Drafts annex for a gated doc type within a repo scope dir."""
    return repo_dir / registry()[key].dir_path / DRAFTS_DIR_NAME


def gated_types() -> list[DocType]:
    """All review-gated doc types (drafts lifecycle applies)."""
    return [dt for dt in registry().values() if dt.gated]


# --- Relation graph queries ------------------------------------------------
# These replace literal per-type registry lookups: a relation with no match
# returns None/empty and the caller skips, which is how a registry with no
# `closes` row gets no closer behavior at all.


def closer_of(dt: DocType, root: Path | None = None) -> DocType | None:
    """The row that closes *dt*, or None when nothing does."""
    for row in registry(root).values():
        if row.closes is not None and row.closes.type == dt.key:
            return row
    return None


def closable_types(root: Path | None = None) -> list[DocType]:
    """Rows something closes (they carry the {stage} lifecycle), in registry
    order."""
    rows = registry(root)
    closed = {
        row.closes.type for row in rows.values() if row.closes is not None
    }
    return [dt for dt in rows.values() if dt.key in closed]


def dependencies_of(dt: DocType) -> DependsOn | None:
    """The row's declared dependency relation, or None."""
    return dt.depends_on
