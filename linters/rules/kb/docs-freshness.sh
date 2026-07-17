#!/usr/bin/env bash
# docs-freshness.sh — Lint rule: kb/docs-freshness
#
# Checks that key kb documents have been modified within the configured
# staleness threshold (default: 30 days). Lists stale files with remediation.
#
# Exit 0 if all key docs are fresh. Exit 1 if any are stale.

set -uo pipefail

PROJECT_ROOT="${1:-$(cd "$(dirname "$0")/../../.." && pwd)}"
LINT_CONFIG="${PROJECT_ROOT}/linters/.lint-config.json"

# Read max_days_stale from config, default 30
MAX_DAYS=30
if [ -f "$LINT_CONFIG" ] && command -v jq &>/dev/null; then
  configured=$(jq -r '.rules["kb/docs-freshness"].max_days_stale // 30' "$LINT_CONFIG")
  if [ "$configured" -gt 0 ] 2>/dev/null; then
    MAX_DAYS="$configured"
  fi
fi

# Discover repo-scoped directories
KEY_DOCS=("AGENTS.md")
for repo_dir in "${PROJECT_ROOT}"/kb/*/; do
  [ -d "$repo_dir" ] || continue
  name=$(basename "$repo_dir")
  [[ "$name" == .* || "$name" == _* ]] && continue
  KEY_DOCS+=(
    "kb/${name}/architecture/ARCHITECTURE.md"
    "kb/${name}/architecture/dependency-rules.md"
    "kb/${name}/golden-principles.md"
    "kb/${name}/quality-scores.md"
    "kb/${name}/tech-debt/index.md"
    "kb/${name}/specs/index.md"
    "kb/${name}/prds/index.md"
  )
  [ -f "${PROJECT_ROOT}/kb/${name}/DESIGN.md" ] && KEY_DOCS+=("kb/${name}/DESIGN.md")
done

FAILED=0
NOW=$(date +%s)
THRESHOLD=$((MAX_DAYS * 86400))

for doc in "${KEY_DOCS[@]}"; do
  full_path="${PROJECT_ROOT}/${doc}"

  if [ ! -f "$full_path" ]; then
    # File doesn't exist — skip (cross-links rule handles missing files)
    continue
  fi

  # Get last modification time
  if stat --version &>/dev/null 2>&1; then
    # GNU stat
    mod_time=$(stat -c '%Y' "$full_path")
  else
    # BSD/macOS stat
    mod_time=$(stat -f '%m' "$full_path")
  fi

  age=$((NOW - mod_time))
  days_old=$((age / 86400))

  if [ "$age" -gt "$THRESHOLD" ]; then
    FAILED=1
    echo "${doc}:1 — Document is ${days_old} days stale (threshold: ${MAX_DAYS} days). Review and update the file content, or run '/update-kb' to refresh kb docs."
  fi
done

if [ "$FAILED" -eq 0 ]; then
  echo "All key kb documents are within the ${MAX_DAYS}-day freshness threshold."
fi

exit "$FAILED"
