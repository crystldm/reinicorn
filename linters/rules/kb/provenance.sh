#!/usr/bin/env bash
# provenance.sh — Lint rule: kb/provenance
#
# Checks that kb .md files have provenance frontmatter (Author, Status,
# Origin) in the first 10 lines. Skips index files, templates, and
# non-document files (README, ATTRIBUTION, quality-scores, etc.).
#
# Exit 0 if all docs have provenance. Exit 1 if any are missing fields.

set -uo pipefail

PROJECT_ROOT="${1:-$(cd "$(dirname "$0")/../../.." && pwd)}"
FAILURES=0

for repo_dir in "${PROJECT_ROOT}"/kb/*/; do
  [ -d "$repo_dir" ] || continue
  name=$(basename "$repo_dir")
  [[ "$name" == .* || "$name" == _* ]] && continue

  while IFS= read -r -d '' file; do
    basename_f=$(basename "$file")

    # Skip non-document files
    case "$basename_f" in
      README.md|ATTRIBUTION.md|index.md|cleanup-queue.md|quality-scores.md|golden-principles.md)
        continue ;;
      progress.md|decisions.md)
        continue ;;
    esac

    # Skip templates
    case "$file" in
      */_template/*) continue ;;
    esac

    # Check first 10 lines for provenance fields
    head_block=$(head -n 10 "$file")
    rel_path="${file#"${PROJECT_ROOT}"/}"
    missing=()

    if ! echo "$head_block" | grep -qi 'author:'; then
      missing+=("Author")
    fi
    if ! echo "$head_block" | grep -qi 'status:'; then
      missing+=("Status")
    fi
    if ! echo "$head_block" | grep -qi 'origin:'; then
      missing+=("Origin")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
      joined=$(IFS=', '; echo "${missing[*]}")
      echo "${rel_path}:1 — Missing provenance field(s): ${joined}. Add frontmatter via 'rcorn <type> create' or manually add Author/Status/Origin fields."
      FAILURES=$((FAILURES + 1))
    fi
  done < <(find "$repo_dir" -name '*.md' -type f -print0)
done

if [ "$FAILURES" -gt 0 ]; then
  exit 1
fi
exit 0
