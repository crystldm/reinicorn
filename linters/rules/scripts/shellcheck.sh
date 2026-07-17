#!/usr/bin/env bash
# lint-shellcheck — Lint rule: scripts/shellcheck
#
# Runs shellcheck on all .sh files in the project, excluding vendored paths
# (.git/, kb/ submodule, .reinicorn/hooks/ copies, .venv/).
#
# Exit 0 if all scripts pass. Exit 1 if any issues found.

set -uo pipefail

PROJECT_ROOT="${1:-$(cd "$(dirname "$0")/../../.." && pwd)}"

# Check if shellcheck is available
if ! command -v shellcheck &>/dev/null; then
  echo "shellcheck not found — skipping. Install with: apt install shellcheck"
  exit 0
fi

# Find all .sh files, excluding paths that shouldn't be linted
mapfile -t scripts < <(
  find "$PROJECT_ROOT" -name '*.sh' -type f \
    -not -path '*/.git/*' \
    -not -path '*/kb/*' \
    -not -path '*/.reinicorn/hooks/*' \
    -not -path '*/.venv/*' \
    | sort
)

if [ ${#scripts[@]} -eq 0 ]; then
  echo "No shell scripts found to check."
  exit 0
fi

FAILED=0

for script in "${scripts[@]}"; do
  # Get path relative to project root for output
  rel_path="${script#"$PROJECT_ROOT"/}"

  # Run the linter and reformat GCC-style output to lint framework format
  # Input format: file:line:col: level: message (SCxxxx)
  while IFS= read -r line; do
    # Parse shellcheck's GCC-style output: file:line:col: severity: message
    if [[ "$line" =~ ^[^:]+:([0-9]+):[0-9]+:\ ([a-z]+):\ (.+)$ ]]; then
      lineno="${BASH_REMATCH[1]}"
      severity="${BASH_REMATCH[2]}"
      message="${BASH_REMATCH[3]}"
      echo "${rel_path}:${lineno} — [${severity}] ${message}"
      FAILED=1
    fi
  done < <(shellcheck -f gcc "$script" 2>&1)
done

if [ "$FAILED" -eq 0 ]; then
  echo "All ${#scripts[@]} shell script(s) pass shellcheck."
fi

exit "$FAILED"
