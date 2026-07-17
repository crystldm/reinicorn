# Claude Code Hooks

Claude Code hooks are **not git hooks**. They are commands that run before or
after Claude Code's agent makes tool calls (file edits, bash commands, commits,
etc.). They enforce project conventions automatically without relying on the
agent to remember every rule.

## How hooks work

A hook is a shell command tied to a tool-call event:

| Hook point     | When it runs                               |
|---------------|--------------------------------------------|
| `PreToolUse`  | Before a tool call executes (can block it) |
| `PostToolUse` | After a tool call completes                |
| `Notification`| When the agent produces a notification     |
| `Stop`        | When the agent finishes its turn           |

Each hook receives a JSON payload on stdin describing the tool call. Exit codes:

- **Exit 0** — proceed normally.
- **Exit 2 (PreToolUse only)** — block the tool call; stdout is fed back as
  an error message.
- **Non-zero (other)** — stdout shown as a warning; execution continues.

## Configuration

Hooks are configured in `.claude/settings.json` under the `hooks` key:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "command": ".claude/hooks/post-edit.sh"
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "command": ".claude/hooks/pre-bash.sh"
      }
    ]
  }
}
```

The `matcher` field is a regex tested against the tool name. If omitted, the
hook runs for every tool call of that type.

## Kb-relevant hook examples

These are optional. Add them incrementally as pain points emerge.

### After a file edit: remind about the active exec plan

```bash
#!/usr/bin/env bash
# .claude/hooks/post-edit-plan-reminder.sh
# PostToolUse hook, matcher: "Edit|Write"

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_params.file_path // .tool_params.filePath // empty')

[ -z "$FILE" ] && exit 0

case "$FILE" in
  */kb/*|*/src/*|*/lib/*)
    echo "Reminder: record any non-obvious decisions in the active exec plan's decisions.md."
    exit 0
    ;;
esac
```

### Before committing: validate kb cross-links

```bash
#!/usr/bin/env bash
# .claude/hooks/pre-commit-validate.sh
# PreToolUse hook, matcher: "Bash"

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_params.command // empty')

case "$COMMAND" in
  *"git commit"*)
    for doc in kb/specs/*.md; do
      [ "$doc" = "kb/specs/index.md" ] && continue
      basename=$(basename "$doc")
      if ! grep -q "$basename" kb/specs/index.md 2>/dev/null; then
        echo "Warning: $basename not listed in kb/specs/index.md"
      fi
    done
    exit 0
    ;;
esac
```

## Important notes

- **Optional.** Start without hooks; add as pain points emerge.
- Hooks run as shell commands in the project root. Keep them fast.
- Exit 2 on PreToolUse **blocks** the tool call — use carefully.
- Scripts must be executable (`chmod +x`).
- Test by piping sample JSON before wiring them up.

## Further reading

See: https://docs.anthropic.com/en/docs/claude-code/hooks
