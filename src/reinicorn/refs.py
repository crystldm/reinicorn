"""The `depends_on` behavior's shared logic: resolve doc references against
the kb's git-tracked paths.

Shared by the ``kb/draft-refs`` lint rule and the ``_pre-push`` dependency
gate so the two can never disagree about whether a reference is approved.
Nothing here knows any doc type by name: which frontmatter field is read,
and which type it must resolve to, come from the row's `DependsOn` relation
(spec: process-as-config §2).

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
from reinicorn.doc_types import DRAFTS_DIR_NAME, registry
from reinicorn.frontmatter import (
    FIELD_STATUS,
    STATUS_DRAFT,
    STATUS_IN_REVIEW,
    get,
)
from reinicorn.git import explain_failure, run_git

if TYPE_CHECKING:
    from pathlib import Path

    from reinicorn.doc_types import DependsOn

# A doc whose dependency field still carries a template placeholder has not
# declared anything. YAML may also parse an unquoted `[...]` placeholder into
# a list, which `declared_dependency` treats the same way. The renderer and
# the matcher live side by side so the create paths that stamp the
# placeholder and the gate that rejects it share one definition.
PLACEHOLDER_RE = re.compile(r"^\[.*\]$")


def dependency_placeholder(rel: DependsOn) -> str:
    """Template text a new doc's dependency field ships with."""
    return f"[kb path to the {rel.type} this implements, or N/A]"


# Explicit opt-out. Case-insensitive so "n/a" and "N/A" both count.
NOT_APPLICABLE = "n/a"
_NOT_APPLICABLE_RE = re.compile(
    rf"{re.escape(NOT_APPLICABLE)}(?:$|\s)", re.IGNORECASE
)

_UNAPPROVED_STATUSES = frozenset({STATUS_DRAFT, STATUS_IN_REVIEW})


def ref_re(root: Path | None = None) -> re.Pattern[str]:
    """Prose matcher for doc references, from the effective registry.

    Anchored on a known doc-type directory rather than on the "kb/" prefix.
    That accepts all three path styles while bounding false positives to
    strings that actually look like doc references. Callers hold the result
    in a local rather than recompiling per line.
    """
    doc_dirs = "|".join(
        re.escape(d)
        for d in sorted(
            {dt.dir_path for dt in registry(root).values() if dt.dir_path != "."}
        )
    )
    return re.compile(
        rf"(?<![\w/])(?:{KB_DIR_NAME}/)?(?:[\w.-]+/)*(?:{doc_dirs})/[\w./-]+\.md"
    )


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
    make every declared dependency look unresolved, which reads as a policy
    violation: the push gate would block with a misleading message and never
    reach its documented loud fail-open path.
    """
    r = run_git("ls-files", "-z", check=False, cwd=kb_dir)
    if r.returncode == 0:
        return frozenset(p for p in r.stdout.split("\0") if p)

    # Only now pay for a second call, to tell the two cases apart. Testing for
    # a `.git` entry would be wrong: the kb is a plain clone in a real
    # checkout, but some test fixtures build it as an ordinary tracked
    # directory instead, and both are enumerable.
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
    internal error for the gate's loud fail-open path, not "every dependency
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
    to a genuinely approved doc still resolves to the approved doc even when a
    same-named draft is tracked too.
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


def path_in_dir(path: str, dir_path: str) -> bool:
    """True when a resolved kb path lives under the doc-type dir *dir_path*.

    The relation names a target *type*, but any tracked doc resolves just as
    well, and a plan.md or README.md carries no review status — so
    `unapproved_reason` finds nothing to object to and the reference sails
    through. Checking the directory is what stops the gate from accepting a
    doc that was never in the lane.

    Drafts count. `specs/drafts/x.md` is a real doc of the type at an
    earlier stage, and reporting it as *unapproved* is far more useful than
    rejecting it as the wrong kind of document.
    """
    return dir_path in path.split("/")[:-1]


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
    if status is None:
        # Legacy doc with no status field — exempt, not malformed.
        return None
    if not isinstance(status, str):
        # `status: []` would raise on set membership; a doc with a mangled
        # status must be a finding, not a crashed lint run or a laundered ref.
        return f"malformed: 'status' is {status!r}, expected a string"
    if status in _UNAPPROVED_STATUSES:
        return f"status '{status}' (approval pending)"
    return None


def declared_dependency(text: str, rel: DependsOn) -> str | None:
    """The doc's declared dependency value, or None when absent/placeholder.

    A non-string value is a placeholder too: YAML parses an unquoted
    ``[kb path …]`` template stub as a list, and no real reference is anything
    but a string.
    """
    value = get(text, rel.field)
    if value is None or not isinstance(value, str):
        return None
    value = value.strip()
    if not value or PLACEHOLDER_RE.match(value):
        return None
    return value


def is_not_applicable(value: str) -> bool:
    """True when the doc declares that it has no dependency.

    A trailing rationale counts: "N/A (fixes two ideas)" is a better
    declaration than a bare "N/A", and a gate that rejects it only teaches
    people to delete the reason. Only a bare "n/a" or one followed by
    whitespace qualifies, so a real path such as "n/a/specs/x.md" stays a
    reference to be resolved rather than an exemption.
    """
    return bool(_NOT_APPLICABLE_RE.match(value.strip().strip("`")))
