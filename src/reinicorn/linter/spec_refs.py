"""Resolve doc references against the kb's git-tracked paths.

Shared by the ``kb/draft-refs`` lint rule and the ``_pre-push`` approval gate so
the two can never disagree about whether a reference is approved.

Resolution is against git, not the filesystem — but the two callers ask about
different revisions, because they answer different questions:

* The **lint** asks "is what I am working on clean?" and resolves against the
  index (:func:`tracked_paths`), so work in progress lints before it is
  committed. In CI the index equals the committed tree.
* The **push gate** asks "is what I am shipping clean?" and resolves against
  the kb commit the pushed branch pins (:func:`tracked_paths_at`), because that
  commit — not the kb index or worktree — is what a reviewer checks out.

Either way, git-emitted paths dispose of two problems by construction:

* **Containment.** Git only ever emits repo-relative paths under the kb root,
  so a reference containing ``..``, an absolute path, or anything outside the
  kb simply fails to match. No caller-supplied string is joined onto a
  filesystem path before it has been proven to name a tracked kb file.
* **Untracked files.** A doc that exists on disk but was never staged (for the
  lint) or committed and pinned (for the gate) is not a real reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from reinicorn.config import KB_DIR_NAME
from reinicorn.doc_types import DRAFTS_DIR_NAME, REGISTRY
from reinicorn.frontmatter import (
    FIELD_SPEC,
    FIELD_STATUS,
    STATUS_DRAFT,
    STATUS_IN_REVIEW,
    get,
)
from reinicorn.git import explain_failure, run_git

if TYPE_CHECKING:
    from pathlib import Path

# Placeholder text the plan template ships with; a plan still carrying it has
# not declared anything. YAML may also parse an unquoted `[...]` placeholder
# into a list, which `declared_spec` treats the same way.
SPEC_PLACEHOLDER_RE = re.compile(r"^\[.*\]$")

# Explicit opt-out. Case-insensitive so "n/a" and "N/A" both count.
SPEC_NOT_APPLICABLE = "n/a"
_NOT_APPLICABLE_RE = re.compile(rf"{re.escape(SPEC_NOT_APPLICABLE)}\b", re.IGNORECASE)

SPEC_DIR_NAME = REGISTRY["spec"].dir_path

# Anchor the prose matcher on a known doc-type directory rather than on the "kb/"
# prefix. That accepts all three path styles while bounding false positives to
# strings that actually look like doc references.
_DOC_DIRS = "|".join(
    re.escape(d)
    for d in sorted({dt.dir_path for dt in REGISTRY.values() if dt.dir_path != "."})
)
REF_RE = re.compile(
    rf"(?<![\w/])(?:{KB_DIR_NAME}/)?(?:[\w.-]+/)*(?:{_DOC_DIRS})/[\w./-]+\.md"
)

_UNAPPROVED_STATUSES = frozenset({STATUS_DRAFT, STATUS_IN_REVIEW})


@dataclass(frozen=True)
class Resolution:
    """Outcome of resolving one reference string.

    Exactly one of ``path`` / ``ambiguous`` is meaningful:

    * ``path`` set          — resolved to a single tracked kb-relative path.
    * ``ambiguous`` set     — candidate forms hit more than one distinct tracked
                              path; the caller must not pick a winner.
    * both empty            — unresolved; no candidate form names a tracked path.
    """

    path: str | None = None
    ambiguous: tuple[str, ...] = ()


def tracked_paths(kb_dir: Path) -> frozenset[str]:
    """kb-relative paths git tracks.

    Empty set when the kb is not a git repo at all — there is nothing to
    resolve against, and callers treat that as "no references resolve".

    A genuine git failure raises instead. Returning an empty set there would
    make every declared spec look unresolved, which reads as a policy violation:
    the push gate would block with a misleading message and never reach its
    documented loud fail-open path.
    """
    r = run_git("ls-files", "-z", check=False, cwd=kb_dir)
    if r.returncode == 0:
        return frozenset(p for p in r.stdout.split("\0") if p)

    # Only now pay for a second call, to tell the two cases apart. Testing for
    # a `.git` entry would be wrong: the kb is a submodule in a real checkout
    # but an ordinary tracked directory in others, and both are enumerable.
    probe = run_git("rev-parse", "--is-inside-work-tree", check=False, cwd=kb_dir)
    if probe.returncode != 0:
        return frozenset()

    # Both callers render this on one line (a lint diagnostic, and the push
    # gate's fail-open notice), so the seam's lines are joined rather than
    # printed as a block — git's own words still survive verbatim.
    raise RuntimeError(
        " ".join(explain_failure(f"enumerate tracked paths in {kb_dir}", r))
    )


def tracked_paths_at(kb_dir: Path, rev: str) -> frozenset[str]:
    """kb-relative paths in the tree of kb revision ``rev``.

    The committed truth: a staged-but-uncommitted doc, a worktree edit, or
    anything newer than ``rev`` is invisible here. A failure raises — ``rev``
    comes from a gitlink the caller just resolved, so an unlistable tree is an
    internal error for the gate's loud fail-open path, not "every spec
    unresolved".
    """
    r = run_git("ls-tree", "-r", "--name-only", "-z", rev, check=False, cwd=kb_dir)
    if r.returncode != 0:
        raise RuntimeError(
            " ".join(explain_failure(f"list the kb tree at {rev}", r))
        )
    return frozenset(p for p in r.stdout.split("\0") if p)


def doc_text_at(kb_dir: Path, rev: str, path: str) -> str:
    """Content of ``rev:path`` in the kb.

    ``path`` must already have been proven present in ``rev``'s tree (via
    :func:`tracked_paths_at`), so a failure here is an internal error too.
    """
    r = run_git("cat-file", "blob", f"{rev}:{path}", check=False, cwd=kb_dir)
    if r.returncode != 0:
        raise RuntimeError(
            " ".join(explain_failure(f"read {path} from kb revision {rev}", r))
        )
    return r.stdout


def _drafts_variant(ref: str) -> str | None:
    """``<dir>/<file>.md`` -> ``<dir>/drafts/<file>.md``, or None if already there."""
    head, sep, tail = ref.rpartition("/")
    if not sep or head.endswith(f"/{DRAFTS_DIR_NAME}") or head == DRAFTS_DIR_NAME:
        return None
    return f"{head}/{DRAFTS_DIR_NAME}/{tail}"


def resolve_ref(ref: str, scope: str, tracked: frozenset[str]) -> Resolution:
    """Resolve one reference string against the tracked-path set.

    ``scope`` is the repo-scope directory of the doc doing the referencing, used
    for the scope-relative form. Candidate forms, all looked up exactly:

    1. ``kb/``-prefixed  — strip the prefix.
    2. kb-relative       — ``reinicorn/specs/x.md``, as written.
    3. scope-relative    — ``specs/x.md`` -> ``<scope>/specs/x.md``.

    The drafts fallback runs only after every exact form misses, so a reference
    to a genuinely approved ``specs/x.md`` still resolves to the approved doc
    even when a same-named draft is tracked too.
    """
    ref = ref.strip().strip("`")
    if not ref:
        return Resolution()

    forms = []
    prefix = f"{KB_DIR_NAME}/"
    if ref.startswith(prefix):
        forms.append(ref[len(prefix):])
    else:
        forms.append(ref)
        if scope:
            forms.append(f"{scope}/{ref}")

    for candidates in (forms, [v for f in forms if (v := _drafts_variant(f))]):
        hits = {c for c in candidates if c in tracked}
        if len(hits) == 1:
            return Resolution(path=next(iter(hits)))
        if len(hits) > 1:
            return Resolution(ambiguous=tuple(sorted(hits)))

    return Resolution()


def is_spec_path(path: str) -> bool:
    """True when a resolved kb path lives under the spec doc-type directory.

    The field names a *spec*, but any tracked doc resolves just as well, and a
    plan.md or README.md carries no review status — so `unapproved_reason` finds
    nothing to object to and the reference sails through. Checking the doc type
    is what stops the gate from accepting a doc that was never in the lane.

    Drafts count as specs. `specs/drafts/x.md` is a real spec at an earlier
    stage, and reporting it as *unapproved* is far more useful than rejecting it
    as the wrong kind of document.
    """
    return SPEC_DIR_NAME in path.split("/")[:-1]


def unapproved_reason(
    path: str, kb_dir: Path, rev: str | None = None
) -> str | None:
    """Why ``path`` is unapproved, or None when it is fine to build on.

    ``path`` must already have been proven tracked by :func:`resolve_ref`.
    With ``rev``, the status is read from that kb revision — the push gate's
    view. Without it, from the worktree — the lint's view — where a tracked
    file missing from disk is a *finding*, not a crash: ``rm`` without
    ``git rm`` is ordinary user state, and the lint runner does not guard
    built-in rules.
    """
    if f"/{DRAFTS_DIR_NAME}/" in f"/{path}":
        return "drafts-annex doc (unapproved; building on a draft needs sign-off)"
    if rev is not None:
        text = doc_text_at(kb_dir, rev, path)
    else:
        try:
            text = (kb_dir / path).read_text()
        except OSError as e:
            return f"tracked but unreadable in the worktree ({e})"
    status = get(text, FIELD_STATUS)
    if status in _UNAPPROVED_STATUSES:
        return f"status '{status}' (approval pending)"
    return None


def declared_spec(text: str) -> str | None:
    """The plan's declared ``spec:`` value, or None when absent/placeholder.

    A non-string value is a placeholder too: YAML parses an unquoted
    ``[kb path …]`` template stub as a list, and no real reference is anything
    but a string.
    """
    value = get(text, FIELD_SPEC)
    if value is None or not isinstance(value, str):
        return None
    value = value.strip()
    if not value or SPEC_PLACEHOLDER_RE.match(value):
        return None
    return value


def is_not_applicable(value: str) -> bool:
    """True when the plan declares that it implements no spec.

    A trailing rationale counts: "N/A (fixes two ideas)" is a better
    declaration than a bare "N/A", and a gate that rejects it only teaches
    people to delete the reason. The word boundary keeps the prefix from
    swallowing a real path — no kb doc directory begins "n/a".
    """
    return bool(_NOT_APPLICABLE_RE.match(value.strip().strip("`")))
