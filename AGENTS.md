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

## Project conventions

- Runtime identity constants live in `reinicorn.identity`.
- KB document-type paths and behavior come from `reinicorn.doc_types.REGISTRY`.
- Validate external input at boundaries and keep one concern per file.
- stdout is the agent-facing result surface; stderr is progress/debug only.
- Follow red-green TDD for behavior changes and use conventional commits.
