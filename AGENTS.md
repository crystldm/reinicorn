# Reinicorn

Reinicorn is a Python CLI and workflow skill set for spec-driven development with
AI coding agents. It serves engineering teams that keep intent, architecture,
plans, and quality controls in a shared Git-backed knowledge base.

## Build and test

- Python 3.12+; dependencies and environments are managed with uv.
- Run the CLI with `rcorn`; use `uv run rcorn` to exercise in-repo changes.
- Run tests with `uv run pytest tests/ -v`.
- Run lint with `uv run ruff check src/reinicorn tests`.
- Run type checking with `uv run pyright src/reinicorn`.
- Run structural and shell checks with `bash tests/run-all.sh` (the runner delegates Python execution through uv).

## Knowledge base

Read and follow `kb/reinicorn/README.md` before planning or changing code. Use
`rcorn` for every KB operation; never manage the KB submodule with raw Git.
This rule applies to agents and contributors operating *on* the KB —
`src/reinicorn/` is the implementation of that interface, and its internal
`run_git` calls are expected.

## Project conventions

- Runtime identity constants live in `reinicorn.identity`.
- KB document-type paths and behavior come from `reinicorn.doc_types.REGISTRY`.
- Validate external input at boundaries and keep one concern per file.
- stdout is the agent-facing result surface; stderr is progress/debug only.
- Follow red-green TDD for behavior changes and use conventional commits.
- Tests assert the protected behavior (the observable side effect), never an
  intermediate signal that merely stands in for it — a sentinel's shape, an
  incidental text blob, or that a flag parsed. Output that is itself the
  contract (e.g. stdout, the agent-facing result surface) is the observable
  behavior — assert it directly. If the guarded outcome is "nothing gets
  archived," the test archives nothing, end to end.
- When code encodes external-system behavior (an API's IDs or enums, a CLI's
  output format), verify against live behavior or docs and cite that evidence
  in the PR — never pattern-guess.

## Pull requests

- Body cites the spec it implements, states verification evidence (test counts,
  the full gate), declares scope boundaries for mid-migration work, and
  discloses known-unrelated noise instead of glossing over it.
- Never claim "always/never/all paths" without enumerating the paths or routing
  them through one enforcing seam.

## Responding to code review

- Verify every finding against current code before acting; findings are a
  starting point for judgment, not a checklist.
- Three valid outcomes, each stated explicitly on the thread: applied (cite the
  commit), deferred (say why), declined (say why). Never a bare dismissal.
- A wrong suggested fix can still point at a real defect — check whether the
  documented contract itself is wrong before rejecting the finding.
- Schema/contract claims are settled by the enforcing code, not spec prose;
  when they disagree, that drift is the finding — surface it, don't silently
  resolve it either way.
- Reviewer memory ("learnings", "addressed" markers) goes stale and can be
  misapplied — re-verify against the current diff, especially across
  force-pushes.
