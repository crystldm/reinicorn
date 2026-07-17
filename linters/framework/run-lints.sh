#!/usr/bin/env bash
# run-lints.sh — Entry point for the Reinicorn linter framework.
#
# Discovers lint rules in rules/, reads .lint-config.json for active rules
# and severity, runs each active rule, and reports results.
#
# Exit 0 if all pass (warnings don't cause failure).
# Exit 1 if any error-severity rule fails.
#
# Requires: jq

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LINTERS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$LINTERS_DIR/.." && pwd)"
LINT_CONFIG="${LINTERS_DIR}/.lint-config.json"

# --- Dependency check ---

if ! command -v jq &>/dev/null; then
  echo "FATAL: 'jq' is required but not installed. Install it with your package manager (e.g., apt install jq)."
  exit 1
fi

# --- Validate config ---

if [ ! -f "$LINT_CONFIG" ]; then
  echo "FATAL: Lint config not found at ${LINT_CONFIG}. Create it from the template in linters/README.md."
  exit 1
fi

if ! jq empty "$LINT_CONFIG" 2>/dev/null; then
  echo "FATAL: ${LINT_CONFIG} is not valid JSON."
  exit 1
fi

# --- Discover rules ---

RULES_DIR="${LINTERS_DIR}/rules"

if [ ! -d "$RULES_DIR" ]; then
  echo "FATAL: Rules directory not found at ${RULES_DIR}."
  exit 1
fi

# --- Run rules ---

TOTAL=0
PASSED=0
FAILED_ERRORS=0
FAILED_WARNINGS=0
SKIPPED=0
ERROR_FAILURES=""
WARNING_FAILURES=""

# Walk rules/ recursively for *.sh files
while IFS= read -r -d '' rule_script; do
  # Derive rule name from path: rules/kb/docs-freshness.sh -> kb/docs-freshness
  rel_path="${rule_script#"${RULES_DIR}/"}"
  rule_name="${rel_path%.sh}"

  # Check if rule is in config
  enabled=$(jq -r --arg name "$rule_name" '.rules[$name].enabled // "null"' "$LINT_CONFIG")

  if [ "$enabled" = "null" ]; then
    # Rule not in config — skip silently
    continue
  fi

  if [ "$enabled" != "true" ]; then
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  severity=$(jq -r --arg name "$rule_name" '.rules[$name].severity // "warning"' "$LINT_CONFIG")

  TOTAL=$((TOTAL + 1))

  # Run the rule, capturing output
  rule_output=""
  rule_output=$("$rule_script" "$PROJECT_ROOT" 2>&1) || rule_exit=$?
  rule_exit=${rule_exit:-0}

  if [ "$rule_exit" -eq 0 ]; then
    PASSED=$((PASSED + 1))
    echo "[PASS] ${rule_name}"
  else
    if [ "$severity" = "error" ]; then
      FAILED_ERRORS=$((FAILED_ERRORS + 1))
      ERROR_FAILURES="${ERROR_FAILURES}\n  - ${rule_name}"
      echo "[FAIL:ERROR] ${rule_name}"
    else
      FAILED_WARNINGS=$((FAILED_WARNINGS + 1))
      WARNING_FAILURES="${WARNING_FAILURES}\n  - ${rule_name}"
      echo "[FAIL:WARNING] ${rule_name}"
    fi
    # Print rule output indented
    if [ -n "$rule_output" ]; then
      while IFS= read -r out_line; do
        echo "    ${out_line}"
      done <<< "$rule_output"
    fi
  fi

  echo ""

done < <(find "$RULES_DIR" -name '*.sh' -type f -print0 | sort -z)

# --- Summary ---

echo "========================================"
echo "Lint Summary"
echo "========================================"
echo "Total rules run: ${TOTAL}"
echo "Passed:          ${PASSED}"
echo "Errors:          ${FAILED_ERRORS}"
echo "Warnings:        ${FAILED_WARNINGS}"
echo "Skipped:         ${SKIPPED}"

if [ "$FAILED_ERRORS" -gt 0 ]; then
  echo ""
  echo "Error-severity failures (must fix):"
  echo -e "$ERROR_FAILURES"
fi

if [ "$FAILED_WARNINGS" -gt 0 ]; then
  echo ""
  echo "Warning-severity failures (should fix):"
  echo -e "$WARNING_FAILURES"
fi

echo "========================================"

# Exit 1 only if error-severity rules failed
if [ "$FAILED_ERRORS" -gt 0 ]; then
  exit 1
fi

exit 0
