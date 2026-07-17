# Lint Rule Template

Use this template when contributing a new lint rule to the framework.

## Rule Metadata

| Field | Value |
|-------|-------|
| **Rule Name** | `category/rule-name` (matches path under `rules/`) |
| **Description** | One-sentence description of what this rule checks |
| **Severity** | `error` or `warning` |
| **Category** | e.g., `kb`, `architecture`, `testing` |

## What It Checks

Describe the invariant this rule enforces. Be specific:
- What files or patterns does it examine?
- What constitutes a pass vs. a failure?
- Are there any edge cases or exceptions?

## Error Message Format

Every message printed by the rule MUST include all four components:

```
{file_path}:{line_number} — {violation_description}. {remediation_instructions}
```

### Components

1. **file_path** — Relative path from project root (e.g., `kb/golden-principles.md`)
2. **line_number** — The line where the violation occurs (use `1` if the issue is file-level)
3. **violation_description** — What is wrong, stated as a fact
4. **remediation_instructions** — Concrete action to fix it, optionally with a reference doc

### Example

```
kb/architecture/ARCHITECTURE.md:1 — Document is 45 days stale (threshold: 30 days). Review and update the file, or run '/update-kb' to refresh.
```

## Implementation

The rule is a shell script at `rules/{category}/{rule-name}.sh`. It must:

1. Be executable (`chmod +x`).
2. Accept the project root directory as `$1` (default: current working directory).
3. Read any rule-specific configuration from `linters/.lint-config.json` if needed
   (requires `jq`).
4. Print agent-readable messages to stdout on failure.
5. Print nothing (or a pass summary) on success.
6. Exit 0 on pass, exit 1 on fail.

### Script Skeleton

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${1:-$(cd "$(dirname "$0")/../../.." && pwd)}"
LINT_CONFIG="${PROJECT_ROOT}/linters/.lint-config.json"

# Read rule-specific config (example)
# MY_OPTION=$(jq -r '.rules["category/rule-name"].my_option // "default"' "$LINT_CONFIG")

FAILED=0

# --- Check logic goes here ---
# For each violation found:
#   echo "path/to/file:LINE — Description. Remediation."
#   FAILED=1

if [ "$FAILED" -eq 1 ]; then
  exit 1
fi

exit 0
```

## Configuration Entry

Add the rule to `linters/.lint-config.json`:

```json
{
  "rules": {
    "category/rule-name": {
      "enabled": true,
      "severity": "warning"
    }
  }
}
```

Add any rule-specific options as additional keys in the rule's config object.

## Checklist Before Submitting

- [ ] Script is executable (`chmod +x`)
- [ ] Script exits 0 on pass, 1 on fail
- [ ] Error messages include file:line, violation, and remediation
- [ ] Configuration entry added to `.lint-config.json`
- [ ] Rule tested against both passing and failing cases
