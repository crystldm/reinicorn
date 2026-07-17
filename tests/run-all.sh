#!/usr/bin/env bash
# Convenience runner for Reinicorn tests.
# Usage: ./tests/run-all.sh [-v] [pytest args...]
set -euo pipefail
cd "$(dirname "$0")/.."
uv run pytest tests/ -v "$@"
