#!/usr/bin/env bash
# cross-links.sh — Lint rule: kb/cross-links
#
# Validates that all markdown file links in AGENTS.md and kb/ point to
# files that actually exist. Reports broken links with exact file:line location
# and remediation suggestion.
#
# Exit 0 if all links resolve. Exit 1 if any broken links are found.

set -uo pipefail

PROJECT_ROOT="${1:-$(cd "$(dirname "$0")/../../.." && pwd)}"

FAILED=0

# Check markdown links in a given file.
# Looks for [text](path) patterns where path is a relative file path
# (not a URL, not an anchor-only link).
check_file() {
  local file="$1"
  local rel_file="${file#"${PROJECT_ROOT}/"}"
  local file_dir
  file_dir="$(dirname "$file")"
  local line_num=0
  local in_fence=0

  while IFS= read -r line; do
    line_num=$((line_num + 1))

    # Toggle fenced-code-block state and skip its contents: links inside
    # ``` fences are illustrative examples, not real references.
    if [[ "${line#"${line%%[![:space:]]*}"}" == '```'* ]]; then
      in_fence=$((1 - in_fence))
      continue
    fi
    if [ "$in_fence" -eq 1 ]; then
      continue
    fi

    # Extract all markdown link targets: [text](target)
    # Use grep to find link patterns, then extract targets
    # This handles multiple links per line
    targets=$(echo "$line" | grep -oP '\[([^\]]*)\]\(([^)]+)\)' | grep -oP '\]\(\K[^)]+' || true)

    for target in $targets; do
      # Skip URLs (http://, https://, mailto:, etc.)
      if echo "$target" | grep -qP '^(https?://|mailto:|ftp://|#)'; then
        continue
      fi

      # Strip anchor fragments (path/file.md#section -> path/file.md)
      link_path="${target%%#*}"

      # Skip empty paths (pure anchor links like #section that were caught above)
      if [ -z "$link_path" ]; then
        continue
      fi

      # Resolve relative to the file's directory
      resolved="${file_dir}/${link_path}"

      # Normalize the path
      if [ ! -e "$resolved" ] && [ ! -d "$resolved" ]; then
        # Also try from project root in case of root-relative paths
        resolved_from_root="${PROJECT_ROOT}/${link_path}"
        if [ ! -e "$resolved_from_root" ] && [ ! -d "$resolved_from_root" ]; then
          FAILED=1
          echo "${rel_file}:${line_num} — Broken link to '${target}'. Target file does not exist. Fix by updating the link path or creating the missing file at '${link_path}'."
        fi
      fi
    done
  done < "$file"
}

# Check AGENTS.md
if [ -f "${PROJECT_ROOT}/AGENTS.md" ]; then
  check_file "${PROJECT_ROOT}/AGENTS.md"
fi

# Check all markdown files under kb/
if [ -d "${PROJECT_ROOT}/kb" ]; then
  while IFS= read -r -d '' md_file; do
    check_file "$md_file"
  done < <(find "${PROJECT_ROOT}/kb" -name '*.md' -type f -print0)
fi

if [ "$FAILED" -eq 0 ]; then
  echo "All markdown cross-links in AGENTS.md and kb/ resolve to existing files."
fi

exit "$FAILED"
