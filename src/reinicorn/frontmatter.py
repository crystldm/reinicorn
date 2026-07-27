"""Read/write/validate the fenced YAML frontmatter block on kb docs.

The ONLY module that touches the `---` block. Every consumer — doc_show,
status, plan, review, the linter, and the create paths — goes through here, so
metadata is never recovered by regex-scanning prose.

Two layers:

- Text-level core (`parse`, `dumps`, `get`, `set_meta`). The review lane reads
  candidate content out of `git show` and never from a path, so the text form
  is primary, not a convenience wrapper.
- Path wrappers (`read`, `write`) for everything that does have a file.

Round-trip stability is a correctness requirement, not an aesthetic one:
`review.push_candidate` asserts the review ref differs from main by exactly one
added file, and `review.candidate_matches_draft` compares exact text. So
`dumps(*parse(text)) == text` must hold for anything this module wrote.
"""

from __future__ import annotations

import datetime as _dt
from typing import TYPE_CHECKING, Any

import yaml

from reinicorn.doc_types import REGISTRY

if TYPE_CHECKING:
    from pathlib import Path

FENCE = "---"

# Enum vocabularies — the ONLY place these strings are defined. Tests assert
# the raw literals on purpose, pinning the on-disk format against typos.
LIFECYCLE_ACTIVE = "active"
LIFECYCLE_DONE = "done"
LIFECYCLE_DROPPED = "dropped"
LIFECYCLES = (LIFECYCLE_ACTIVE, LIFECYCLE_DONE, LIFECYCLE_DROPPED)

ORIGIN_HUMAN = "human"
ORIGIN_AI = "ai-assisted"
ORIGINS = (ORIGIN_HUMAN, ORIGIN_AI)

STATUS_DRAFT = "draft"
STATUS_IN_REVIEW = "in-review"
STATUS_APPROVED = "approved"

# Core fields every doc carries, in canonical serialization order.
CORE_ORDER = (
    "type", "title", "slug", "lifecycle", "status",
    "created", "updated", "author", "origin", "human_validated",
)
CORE_REQUIRED = (
    "type", "title", "slug", "lifecycle", "status", "created", "author",
)
# Serialized last: the aggregation/mining substrate.
TRAILING_ORDER = ("tags", "related")

# Per-type fields, keyed by doc_types.REGISTRY key. `type:` uses the registry
# key itself (`plan`, `debt`) rather than a second vocabulary, so enum
# validation is `meta["type"] in REGISTRY`.
PER_TYPE: dict[str, tuple[str, ...]] = {
    "plan": ("branch", "ticket", "spec", "retro"),
    "retro": ("branch", "plan"),
    "idea": ("promoted_to",),
    "spec": ("supersedes", "superseded_by", "implemented_by"),
    "prd": ("supersedes", "superseded_by", "implemented_by"),
    "debt": ("id", "category", "severity", "remediation"),
    "principle": (),
}
PER_TYPE_REQUIRED: dict[str, tuple[str, ...]] = {
    "plan": ("branch",),
    "retro": ("branch",),
}
# Review-lane stamps, allowed only on review-gated types.
REVIEW_FIELDS = ("review_pr", "approved_by", "review_cancelled")

# Non-doc files: dashboards, indexes, and team-owned prose that carry no
# provenance. One list, shared by the migration and the lint rule.
EXCLUDED_FILENAMES = frozenset({
    "README.md", "index.md", "ATTRIBUTION.md", "quality-scores.md",
    "cleanup-queue.md", "progress.md", "decisions.md",
})
# Directories holding aggregates rather than authored docs. `by-category`
# rolls tech-debt items up per category (## High → ### SEC-08 …) and
# `references` holds how-tos that no REGISTRY type claims — neither has an
# author or a lifecycle, and the spec's Non-Goals rule out inventing a type
# for them. Verified against the corpus 2026-07-27.
EXCLUDED_DIRS = frozenset({"_template", "by-category", "references"})


def _allowed_keys(doc_type: str | None) -> set[str]:
    keys = set(CORE_ORDER) | set(TRAILING_ORDER)
    keys |= set(PER_TYPE.get(doc_type or "", ()))
    if doc_type in REGISTRY and REGISTRY[doc_type].gated:
        keys |= set(REVIEW_FIELDS)
    return keys


def _key_order(meta: dict[str, Any]) -> list[str]:
    """Canonical order: core, per-type, review stamps, then tags/related.

    Unknown keys are appended (sorted) rather than dropped, so a hand-edited
    field survives a round trip and `validate` can report it.
    """
    doc_type = meta.get("type")
    per_type = PER_TYPE.get(doc_type or "", ())
    review = REVIEW_FIELDS if (
        doc_type in REGISTRY and REGISTRY[doc_type].gated
    ) else ()
    ordered = [
        k for k in (*CORE_ORDER, *per_type, *review, *TRAILING_ORDER)
        if k in meta
    ]
    return ordered + sorted(set(meta) - set(ordered))


def _coerce_dates(meta: dict[str, Any]) -> dict[str, Any]:
    """Normalize datetimes to plain dates.

    Dates stay as `datetime.date`, never strings: safe_dump of the *string*
    "2026-07-19" emits it quoted, to preserve its type on reload.
    """
    return {
        k: v.date() if isinstance(v, _dt.datetime) else v
        for k, v in meta.items()
    }


def parse(text: str) -> tuple[dict[str, Any], str]:
    """(meta, body). Returns ({}, text) when there is no frontmatter fence.

    `body` is everything after the closing fence line, verbatim — including its
    leading newline — so `dumps` can reassemble the file byte-for-byte.
    """
    if not text.startswith(FENCE + "\n"):
        return {}, text
    end = text.find("\n" + FENCE + "\n", len(FENCE))
    if end == -1:
        return {}, text
    block = text[len(FENCE) + 1:end + 1]
    body = text[end + len(FENCE) + 2:]
    try:
        meta = yaml.safe_load(block)
    except yaml.YAMLError:
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    return _coerce_dates(meta), body


def dumps(meta: dict[str, Any], body: str) -> str:
    """Serialize to `---\\n<yaml>---\\n<body>` with stable key ordering."""
    ordered = {k: meta[k] for k in _key_order(meta)}
    block = yaml.safe_dump(
        ordered,
        sort_keys=False,        # _key_order owns the ordering
        allow_unicode=True,     # keep em dashes readable, not \u escapes
        default_flow_style=False,
        width=float("inf"),     # never fold long values onto continuations
    )
    return f"{FENCE}\n{block}{FENCE}\n{body}"


def get(text: str, key: str) -> Any | None:
    return parse(text)[0].get(key)


def set_meta(text: str, updates: dict[str, Any]) -> str:
    """Apply updates to the frontmatter, leaving the body untouched.

    A value of None removes the key (used to clear review-lane stamps).
    """
    meta, body = parse(text)
    for key, value in updates.items():
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value
    return dumps(meta, body)


def validate(meta: dict[str, Any]) -> list[str]:
    """Required-field, enum, and type checks. Empty list means valid."""
    if not meta:
        return ["no frontmatter block found"]

    errors: list[str] = []
    doc_type = meta.get("type")

    for field in CORE_REQUIRED:
        if meta.get(field) in (None, ""):
            errors.append(f"missing required field '{field}'")

    if doc_type is not None and doc_type not in REGISTRY:
        errors.append(
            f"'type' must be one of {sorted(REGISTRY)}, got '{doc_type}'"
        )

    lifecycle = meta.get("lifecycle")
    if lifecycle is not None and lifecycle not in LIFECYCLES:
        errors.append(
            f"'lifecycle' must be one of {list(LIFECYCLES)}, got '{lifecycle}'"
        )

    origin = meta.get("origin")
    if origin is not None and origin not in ORIGINS:
        errors.append(
            f"'origin' must be one of {list(ORIGINS)}, got '{origin}'"
        )

    for field in ("created", "updated"):
        value = meta.get(field)
        if value is not None and not isinstance(value, _dt.date):
            errors.append(f"'{field}' must be a date, got {value!r}")

    if "human_validated" in meta and not isinstance(
        meta["human_validated"], bool
    ):
        errors.append("'human_validated' must be true or false")

    for field in TRAILING_ORDER:
        value = meta.get(field)
        if value is None:
            continue
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            errors.append(f"'{field}' must be a list of strings")

    for field in PER_TYPE_REQUIRED.get(doc_type or "", ()):
        if meta.get(field) in (None, ""):
            errors.append(
                f"'{doc_type}' docs require '{field}'"
            )

    allowed = _allowed_keys(doc_type)
    for key in sorted(set(meta) - allowed):
        errors.append(f"unknown field '{key}' for type '{doc_type}'")

    return errors


def read(path: Path) -> tuple[dict[str, Any], str]:
    return parse(path.read_text())


def write(path: Path, meta: dict[str, Any], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(meta, body))


def is_doc(path: Path) -> bool:
    """Whether a kb file is a provenance-carrying doc.

    Dashboards, indexes, and templates are excluded — they have no author or
    lifecycle and never did.
    """
    if path.suffix != ".md":
        return False
    if path.name in EXCLUDED_FILENAMES:
        return False
    return not EXCLUDED_DIRS.intersection(path.parts)
