"""rcorn _process-gate <branch> — the pre-merge CI check.

Runs exactly the required-sections, draft-refs and closer-filled rules,
scoped to the docs the named branch owns (spec: process-as-config §3).
``kb/lifecycle`` is excluded by design: the branch under review is
unmerged, and other branches' staleness must not red this PR. A branch
with no governed docs passes untouched.

The rules are the same classes `rcorn kb lint` runs; the gate filters
their diagnostics to the branch's paths rather than walking the kb a
second way. Config severity does not apply here — every finding blocks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from reinicorn import console
from reinicorn.config import kb_scope
from reinicorn.corpus import doc_path
from reinicorn.doc_types import Addressing, filename_placeholders, registry
from reinicorn.git import current_branch, repo_root
from reinicorn.kb import get_kb_dir
from reinicorn.linter.rules.base import diagnostic_path
from reinicorn.linter.rules.closer_filled import CloserFilledRule
from reinicorn.linter.rules.doc_structure import DocStructureRule
from reinicorn.linter.rules.draft_refs import DraftRefsRule
from reinicorn.staging import STAGES, branch_dir

if TYPE_CHECKING:
    from pathlib import Path

GATE_RULES = (DocStructureRule, DraftRefsRule, CloserFilledRule)


def cmd_process_gate(argv: list[str]) -> int:
    branch = argv[0] if argv else current_branch()
    if not branch:
        console.error("no branch to gate: rcorn _process-gate <branch>")
        return 2

    root = repo_root()
    if root is None:
        return 1
    kb_dir = get_kb_dir(root)
    if kb_dir is None:
        console.warn("Process gate: no kb checkout — nothing to check.")
        return 0

    docs = branch_docs(root, kb_dir, branch)
    console.header(f"Process gate: branch '{branch}'")
    if not docs:
        console.success("No governed docs on this branch — pass.")
        return 0
    for rel in sorted(docs):
        console.info(f"  {rel}")
    print()

    failed: list[str] = []
    for rule_cls in GATE_RULES:
        rule = rule_cls()
        hits = [d for d in rule.run(root) if diagnostic_path(d) in docs]
        if not hits:
            print(f"[PASS] {rule.name()}")
            continue
        failed.append(rule.name())
        print(f"[FAIL] {rule.name()}")
        for d in hits:
            print(f"    {d}")
    print()
    if failed:
        console.error(f"process gate failed: {', '.join(failed)}")
        return 1
    console.success("Process gate passed.")
    return 0


def branch_docs(root: Path, kb_dir: Path, branch: str) -> set[str]:
    """Project-relative paths of every governed doc *branch* owns in this
    repo's scope: the branch dirs of every closable type at any stage
    (closers ride inside), plus each other branch-addressed row's doc.

    A closee doc that *should* exist is included even when the file is
    missing, so the structure rule's "missing doc" finding is not filtered
    away.
    """
    scope_dir = kb_dir / kb_scope(root)
    found: set[Path] = set()
    for dt in registry(root).values():
        if dt.addressing is not Addressing.BRANCH or dt.closes is not None:
            continue
        if "stage" in filename_placeholders(dt):
            doc_name = dt.filename.rsplit("/", 1)[-1]
            for stage in STAGES:
                d = branch_dir(scope_dir, dt, branch, stage)
                if not d.is_dir():
                    continue
                found.add(d / doc_name)
                found.update(p for p in d.iterdir() if p.is_file())
            continue
        p = doc_path(scope_dir, dt, branch)
        if p.is_file():
            found.add(p)
    return {p.relative_to(root).as_posix() for p in found}
