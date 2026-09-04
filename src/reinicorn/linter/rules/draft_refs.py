"""Lint rule: active docs must not build on unapproved (draft/in-review) docs.

Runs for every registry row with a `depends_on` relation (spec:
process-as-config §2): the declared field must resolve to an approved doc
of the target type (or N/A), and the body's prose references are the
backstop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from reinicorn.config import KB_DIR_NAME
from reinicorn.corpus import iter_docs
from reinicorn.doc_types import filename_regex, registry
from reinicorn.linter.rules.base import LintRule
from reinicorn.refs import (
    declared_dependency,
    is_not_applicable,
    path_in_dir,
    ref_re,
    resolve_ref,
    tracked_paths,
    unapproved_reason,
)
from reinicorn.staging import STAGE_ACTIVE

if TYPE_CHECKING:
    from pathlib import Path
    from re import Pattern

    from reinicorn.doc_types import DocType


class DraftRefsRule(LintRule):
    def name(self) -> str:
        return f"{KB_DIR_NAME}/draft-refs"

    def run(self, project_root: Path) -> list[str]:
        diagnostics: list[str] = []
        kb = project_root / KB_DIR_NAME
        if not kb.is_dir():
            return diagnostics

        # The runner does not guard built-in rules, so an unreadable kb must
        # become a diagnostic rather than crash the whole lint run.
        try:
            tracked = tracked_paths(kb)
        except RuntimeError as e:
            return [f"{KB_DIR_NAME}:1 — cannot enumerate tracked kb paths: {e}"]

        # Path-matched, not type-matched: a doc with broken frontmatter must
        # still be checked, and completed-stage docs must not be. The
        # pattern's own regex keeps placeholders within one path segment —
        # fnmatch would let `*` cross `/` and lint nested lookalikes.
        rows: list[tuple[DocType, Pattern[str]]] = []
        for dt in registry(project_root).values():
            if dt.depends_on is None:
                continue
            pattern = dt.filename.replace("{stage}", STAGE_ACTIVE)
            rows.append((dt, filename_regex(f"{dt.dir_path}/{pattern}")))
        if not rows:
            return diagnostics

        prose_re = ref_re(project_root)
        for doc in iter_docs(kb):
            rel_scope = doc.path.relative_to(kb / doc.scope).as_posix()
            hit = next(
                (dt for dt, rx in rows if rx.fullmatch(rel_scope)), None,
            )
            if hit is None or hit.depends_on is None:
                continue
            rel = doc.path.relative_to(project_root)
            text = doc.path.read_text()

            # Report each offending doc once per referencing doc. A doc named
            # in the declared field and again in prose is one violation, not
            # two.
            seen: set[str] = set()

            diagnostics.extend(self._check_declared(
                text, hit, rel, doc.scope, kb, tracked, seen, project_root,
            ))
            diagnostics.extend(self._check_prose(
                text, prose_re, rel, doc.scope, kb, tracked, seen,
            ))

        return diagnostics

    def _check_declared(
        self, text: str, dt: DocType, rel: Path, scope: str, kb: Path,
        tracked: frozenset[str], seen: set[str], project_root: Path,
    ) -> list[str]:
        """Validate the declared dependency frontmatter field.

        A missing field is itself a finding — omitting the reference must not be
        a way to dodge the gate. ``N/A`` is the explicit, reviewable opt-out.
        """
        dep = dt.depends_on
        if dep is None:
            return []
        value = declared_dependency(text, dep)
        if value is None:
            return [
                f"{rel}:1 — no '{dep.field}:' frontmatter field (declare the "
                f"{dep.type} this {dt.key} implements, or 'N/A' if it "
                "intentionally has none)"
            ]
        if is_not_applicable(value):
            return []

        res = resolve_ref(value, scope, tracked)
        if res.ambiguous:
            return [
                f"{rel}:1 — '{dep.field}: {value}' is ambiguous; it matches "
                f"{', '.join(res.ambiguous)}"
            ]
        if res.path is None:
            return [
                f"{rel}:1 — '{dep.field}: {value}' matches no git-tracked kb "
                "path (typo, uncommitted doc, or a path outside the kb)"
            ]

        # The project's registry, like `run` — cwd-resolved lookup could
        # judge this kb by another checkout's overlay.
        target_dir = registry(project_root)[dep.type].dir_path
        if not path_in_dir(res.path, target_dir):
            return [
                f"{rel}:1 — '{dep.field}: {value}' resolves to '{res.path}', "
                f"which is not a {dep.type}; name a doc under "
                f"'{target_dir}/' or 'N/A'"
            ]

        seen.add(res.path)
        reason = unapproved_reason(res.path, kb)
        if reason:
            return [
                f"{rel}:1 — declared {dep.type} '{res.path}' is {reason}"
            ]
        return []

    def _check_prose(
        self, text: str, prose_re: Pattern[str], rel: Path, scope: str,
        kb: Path, tracked: frozenset[str], seen: set[str],
    ) -> list[str]:
        """Backstop: scan the body for references to unapproved docs.

        Catches a doc that declares ``N/A`` but builds on a draft anyway.
        Unresolvable prose strings are ignored here — prose is not a contract,
        and only the declared field is held to that standard.
        """
        diagnostics: list[str] = []
        in_fence = False

        for n, line in enumerate(text.splitlines(), 1):
            # Fenced blocks hold illustrative example paths, not real
            # references — mirror cross_links' fence-skipping.
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue

            for ref in prose_re.findall(line):
                res = resolve_ref(ref, scope, tracked)
                if res.path is None or res.path in seen:
                    continue
                reason = unapproved_reason(res.path, kb)
                if reason:
                    seen.add(res.path)
                    diagnostics.append(f"{rel}:{n} — references '{res.path}': {reason}")

        return diagnostics
