"""One walk over the governed doc corpus, and one path contract.

`iter_docs` is the only place the kb layout is walked: lint rules, gates
and the dashboard iterate `Doc`s instead of hand-rolling
``kb/*/exec-plans/active`` globs, so no rule can rebuild the layout by
hand (spec: process-as-config §2c). `doc_path` is the only path
computation for a doc addressed by its identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from reinicorn import frontmatter
from reinicorn.doc_types import DocType, filename_placeholders, registry
from reinicorn.kb import branch_dir_name

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# Kb top-level dirs that hold generated or shared material, not scopes.
_NON_SCOPE_PREFIXES = (".", "_")
_GENERATED_DIR = "generated"


@dataclass(frozen=True)
class Doc:
    """A governed kb doc, paired with its registry row and parsed parts.

    `dt` is None for a doc whose `type:` frontmatter names no registry row
    (including a missing or unparseable block) — rules that need a row
    filter on it; the frontmatter rule reports it.
    """

    path: Path
    scope: str
    dt: DocType | None
    meta: dict[str, Any]
    body: str


def iter_scope_dirs(kb: Path) -> Iterator[Path]:
    """The repo-scope dirs inside a kb clone, in sorted order."""
    if not kb.is_dir():
        return
    for entry in sorted(kb.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(_NON_SCOPE_PREFIXES):
            continue
        if entry.name == _GENERATED_DIR:
            continue
        yield entry


def iter_docs(kb: Path, scope: str | None = None) -> Iterator[Doc]:
    """Every governed doc in the kb (or one scope), with row and frontmatter.

    "Governed" is `frontmatter.is_doc`: dashboards, indexes, templates and
    non-markdown files are not docs and are never yielded.
    """
    # The kb clone lives at <root>/kb, so the project root is its parent.
    reg = registry(kb.parent)
    for scope_dir in iter_scope_dirs(kb):
        if scope is not None and scope_dir.name != scope:
            continue
        for path in sorted(scope_dir.rglob("*.md")):
            if not frontmatter.is_doc(path):
                continue
            meta, body = frontmatter.read(path)
            dt = reg.get(meta.get("type")) if meta else None
            yield Doc(
                path=path, scope=scope_dir.name, dt=dt, meta=meta, body=body,
            )


def doc_path(
    repo_dir: Path, dt: DocType, ident: str | None = None,
) -> Path:
    """The path of a doc addressed by its identity, inside a scope dir.

    `ident` is whatever the row's addressing consumes: the branch for
    branch-addressed rows (sanitized here), the slug for slug-addressed
    rows, nothing for singletons. A filename needing more than the identity
    ({seq} is allocated at create, {username} chosen at create) cannot be
    formatted after the fact — resolve those through `iter_docs` matching
    on `id`/slug instead; this raises rather than guess.
    """
    placeholders = filename_placeholders(dt)
    extra = placeholders - {"slug", "branch"}
    if extra:
        raise ValueError(
            f"doc_path cannot resolve a '{dt.key}' path: filename "
            f"'{dt.filename}' needs {sorted(extra)}, which only creation "
            "knows — look the doc up via iter_docs instead"
        )
    values: dict[str, str] = {}
    if "branch" in placeholders:
        if ident is None:
            raise ValueError(f"'{dt.key}' is branch-addressed: pass a branch")
        values["branch"] = branch_dir_name(ident)
    if "slug" in placeholders:
        if ident is None:
            raise ValueError(f"'{dt.key}' is slug-addressed: pass a slug")
        values["slug"] = ident
    return repo_dir / dt.dir_path / dt.filename.format(**values)


def iter_branch_dirs(kb: Path, dt: DocType) -> Iterator[tuple[str, Path]]:
    """(scope, branch dir) for every branch dir of a branch-addressed type.

    The branch dir is the parent the filename pattern puts the doc in
    (``active/{branch}/plan.md`` → each dir under ``active/``). Yields the
    dir whether or not the doc file exists — the structure lint needs the
    empty-dir case.
    """
    pattern = dt.filename.replace("{branch}", "*")
    parent_pattern = pattern.rsplit("/", 1)[0] if "/" in pattern else None
    if parent_pattern is None:
        return
    for scope_dir in iter_scope_dirs(kb):
        base = scope_dir / dt.dir_path
        if not base.is_dir():
            continue
        for d in sorted(base.glob(parent_pattern)):
            if d.is_dir():
                yield scope_dir.name, d
