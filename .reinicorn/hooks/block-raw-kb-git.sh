#!/usr/bin/env bash
# block-raw-kb-git.sh — PreToolUse hook for shell tools
#
# Blocks agents from running git commands directly inside the kb/
# submodule directory. This surfaces Reinicorn CLI failures instead of
# letting agents silently work around them.
#
# Gating is presence-based, not tool-name-based: editors name their
# shell tool differently (Claude Code: Bash; Cursor/Copilot: terminal,
# run_terminal_cmd, shell, ...), so instead of an allowlist of tool
# names we act whenever the tool input carries a shell command string
# and no-op otherwise. This stays portable across editors and cannot
# fail open on an unrecognized tool name.
#
# Allowed: uv run rcorn kb publish, uv run rcorn kb sync, uv run rcorn kb git
# Blocked: cd kb && git ..., git -C kb/ ...
#
# Exit 0 = allow, Exit 2 = block

INPUT=$(cat)

# Act only when a shell command payload is present (any shell tool);
# tools without one (Write, Edit, ...) no-op.
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // .tool_input.cmd // empty')
[ -z "$CMD" ] && exit 0

# Block: cd kb && git ... or cd kb; git ...
# Block: git -C kb ...
# Block: git -C ./kb ...
# Block: (cd kb && git ...)
if echo "$CMD" | grep -qP '((cd|pushd)\s+(\./)?kb[/\s;].*git\b|git\s+-C\s+(\./)?kb)'; then
  echo "Blocked: direct git commands in the kb directory." >&2
  echo "" >&2
  echo "Use Reinicorn CLI instead:" >&2
  echo "  uv run rcorn kb publish      — push kb changes" >&2
  echo "  uv run rcorn kb sync         — pull kb changes" >&2
  echo "  uv run rcorn kb git …        — escape hatch for raw git" >&2
  exit 2
fi

exit 0
