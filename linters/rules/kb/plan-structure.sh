#!/usr/bin/env bash
# plan-structure.sh — Lint rule: kb/plan-structure
#
# Validates that active execution plans have the required sections
# (Goal, Acceptance Criteria, Tasks).
#
# Exit 0 if all active plans are well-formed. Exit 1 if any are invalid.

set -uo pipefail

PROJECT_ROOT="${1:-$(cd "$(dirname "$0")/../../.." && pwd)}"
KB_DIR="${PROJECT_ROOT}/kb"

if [ ! -d "$KB_DIR" ]; then
  echo "No kb directory found. Nothing to check."
  exit 0
fi

FAILED=0
PLANS_CHECKED=0

for repo_dir in "$KB_DIR"/*/; do
  [ -d "$repo_dir" ] || continue
  repo_name="$(basename "$repo_dir")"
  [[ "$repo_name" == .* || "$repo_name" == _* ]] && continue
  ACTIVE_DIR="${repo_dir}exec-plans/active"
  [ -d "$ACTIVE_DIR" ] || continue

  for plan_dir in "$ACTIVE_DIR"/*/; do
    [ -d "$plan_dir" ] || continue
    branch_name="$(basename "$plan_dir")"
    plan_file="${plan_dir}plan.md"
    rel_plan="kb/${repo_name}/exec-plans/active/${branch_name}/plan.md"

    PLANS_CHECKED=$((PLANS_CHECKED + 1))

    # Check plan.md exists
    if [ ! -f "$plan_file" ]; then
      FAILED=1
      echo "${rel_plan}:1 — Missing plan.md in active exec plan '${branch_name}'. Create it using the template at kb/exec-plans/_template/plan.md."
    else
      # Check required sections: Goal, Acceptance Criteria, Tasks
      if ! grep -qiP '^\s*##\s+Goal' "$plan_file"; then
        FAILED=1
        line=$(grep -n '##' "$plan_file" | head -1 | cut -d: -f1)
        line=${line:-1}
        echo "${rel_plan}:${line} — Missing required '## Goal' section. Add a '## Goal' heading describing what this branch is building or fixing."
      fi

      if ! grep -qiP '^\s*##\s+Acceptance\s+Criteria' "$plan_file"; then
        FAILED=1
        line=$(grep -n '##' "$plan_file" | tail -1 | cut -d: -f1)
        line=${line:-1}
        echo "${rel_plan}:${line} — Missing required '## Acceptance Criteria' section. Add a '## Acceptance Criteria' heading with a checklist of success conditions."
      fi

      if ! grep -qiP '^\s*##\s+Tasks' "$plan_file"; then
        FAILED=1
        line=$(grep -n '##' "$plan_file" | tail -1 | cut -d: -f1)
        line=${line:-1}
        echo "${rel_plan}:${line} — Missing required '## Tasks' section. Add a '## Tasks' heading with a checklist of work items."
      fi
    fi
  done
done

if [ "$PLANS_CHECKED" -eq 0 ]; then
  echo "No active execution plans found. Nothing to validate."
  exit 0
fi

if [ "$FAILED" -eq 0 ]; then
  echo "All ${PLANS_CHECKED} active execution plan(s) have required sections."
fi

exit "$FAILED"
