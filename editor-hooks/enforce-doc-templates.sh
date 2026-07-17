#!/usr/bin/env bash
# enforce-doc-templates.sh — PreToolUse hook for Write|Edit
#
# Portable across Claude Code, VS Code Copilot, and Cursor.
# Delegates to 'uv run rcorn _check-path' so all protected path logic
# lives in Python (single source of truth).
#
# Exit 0 = allow, Exit 2 = block

INPUT=$(cat)

# Tool name check — Copilot ignores matchers so hook fires for ALL tools.
# Must filter here to avoid overhead on non-write tool calls.
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
case "$TOOL" in
  Write|Edit|write|edit|editFiles|file_edit) ;;
  *) exit 0 ;;
esac

# Extract file path — all three editors use .tool_input:
#   Claude Code: .tool_input.file_path
#   Cursor:      .tool_input.file_path / .tool_input.filePath
#   Copilot:     .tool_input.file_path / .tool_input.files[0]
FILE=$(echo "$INPUT" | jq -r '
  .tool_input.file_path //
  .tool_input.filePath //
  (.tool_input.files // [])[0] //
  empty
')

[ -z "$FILE" ] && exit 0

# Only check .md files in kb dirs to avoid overhead
# shellcheck disable=SC2221,SC2222
case "$FILE" in
  *kb/*.md | *kb/*/*.md | *kb/*/*/*.md | *kb/*/*/*/*.md)
    ;;
  *)
    exit 0
    ;;
esac

# Delegate to Reinicorn CLI (single source of truth for protected paths)
uv run rcorn _check-path "$FILE"
