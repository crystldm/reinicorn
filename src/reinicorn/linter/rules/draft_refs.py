"""Lint rule: active plans must not build on unapproved (draft/in-review) docs."""

from __future__ import annotations

from fnmatch import fnmatch
from typing import TYPE_CHECKING

from reinicorn.config import KB_DIR_NAME
from reinicorn.corpus import iter_docs
from reinicorn.doc_types import registry
from reinicorn.linter.rules.base import LintRule
from reinicorn.linter.spec_refs import (
    declared_spec,
    is_not_applicable,
    is_spec_path,
    ref_re,
    resolve_ref,
    spec_dir_name,
    tracked_paths,
    unapproved_reason,
)

if TYPE_CHECKING:
    from pathlib import Path


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

        plan_dt = registry(project_root).get("plan")
        if plan_dt is None:
            return diagnostics
        # Path-matched, not type-matched: a plan.md with broken frontmatter
        # must still be checked, and completed plans must not be.
        active_rel = f"{plan_dt.dir_path}/{plan_dt.filename.replace('{branch}', '*')}"
        for doc in iter_docs(kb):
            if not fnmatch(
                str(doc.path.relative_to(kb / doc.scope)), active_rel
            ):
                continue
            rel = doc.path.relative_to(project_root)
            scope = doc.scope
            text = doc.path.read_text()

            # Report each offending doc once per plan. A spec named in the
            # spec: field and again in prose is one violation, not two.
            seen: set[str] = set()

            diagnostics.extend(
                self._check_declared(text, rel, scope, kb, tracked, seen)
            )
            diagnostics.extend(
                self._check_prose(text, rel, scope, kb, tracked, seen)
            )

        return diagnostics

    def _check_declared(
        self, text: str, rel: Path, scope: str, kb: Path,
        tracked: frozenset[str], seen: set[str],
    ) -> list[str]:
        """Validate the declared spec: frontmatter field.

        A missing field is itself a finding — omitting the reference must not be
        a way to dodge the gate. ``N/A`` is the explicit, reviewable opt-out.
        """
        value = declared_spec(text)
        if value is None:
            return [
                f"{rel}:1 — no 'spec:' frontmatter field (declare the spec this plan "
                "implements, or 'N/A' if it intentionally has none)"
            ]
        if is_not_applicable(value):
            return []

        res = resolve_ref(value, scope, tracked)
        if res.ambiguous:
            return [
                f"{rel}:1 — 'spec: {value}' is ambiguous; it matches "
                f"{', '.join(res.ambiguous)}"
            ]
        if res.path is None:
            return [
                f"{rel}:1 — 'spec: {value}' matches no git-tracked kb path "
                "(typo, uncommitted doc, or a path outside the kb)"
            ]

        if not is_spec_path(res.path):
            return [
                f"{rel}:1 — 'spec: {value}' resolves to '{res.path}', which "
                f"is not a spec; name a doc under '{spec_dir_name()}/' or 'N/A'"
            ]

        seen.add(res.path)
        reason = unapproved_reason(res.path, kb)
        if reason:
            return [f"{rel}:1 — declared spec '{res.path}' is {reason}"]
        return []

    def _check_prose(
        self, text: str, rel: Path, scope: str, kb: Path,
        tracked: frozenset[str], seen: set[str],
    ) -> list[str]:
        """Backstop: scan the body for references to unapproved docs.

        Catches a plan that declares ``N/A`` but builds on a draft anyway.
        Unresolvable prose strings are ignored here — prose is not a contract,
        and only the declared field is held to that standard.
        """
        diagnostics: list[str] = []
        in_fence = False
        prose_ref_re = ref_re()

        for n, line in enumerate(text.splitlines(), 1):
            # Fenced blocks hold illustrative example paths, not real
            # references — mirror cross_links' fence-skipping.
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue

            for ref in prose_ref_re.findall(line):
                res = resolve_ref(ref, scope, tracked)
                if res.path is None or res.path in seen:
                    continue
                reason = unapproved_reason(res.path, kb)
                if reason:
                    seen.add(res.path)
                    diagnostics.append(f"{rel}:{n} — references '{res.path}': {reason}")

        return diagnostics
