# Linter Framework

## What Is This?

A stack-agnostic, discoverable lint rule framework for the Reinicorn kb. Each lint
rule is a standalone shell script that checks one specific aspect of kb health.
Rules are discovered automatically by scanning the `rules/` directory tree, configured
via `.lint-config.json`, and run by a single entry-point script.

The framework is designed for both human and AI agent consumption. Every error message
follows an agent-readable convention so that coding agents can parse failures, locate
the relevant file and line, understand the violation, and apply the fix autonomously.

## How Rules Are Discovered and Run

1. `framework/run-lints.sh` reads `.lint-config.json` to determine which rules are
   enabled and their severity levels.
2. It walks the `rules/` directory recursively, finding all `*.sh` files.
3. Each script's path maps to a rule name: `rules/kb/docs-freshness.sh` maps
   to the rule `kb/docs-freshness`.
4. If a rule is enabled in config, the script is executed. If a rule is not listed
   in config, it is skipped.
5. Results are collected: exit code 0 means pass, exit code 1 means fail.
6. The framework exits 0 if all rules pass or only warnings fail. It exits 1 if
   any rule with `"severity": "error"` fails.

## Agent-Readable Error Message Convention

Every lint rule MUST produce error messages that an AI coding agent can act on without
further context. Messages must include:

- **File path** with line number
- **Violation description** (what is wrong)
- **Remediation instructions** (how to fix it)

### Bad

```
Import violation in billing/service.ts
```

This tells the agent *what* but not *where*, *why*, or *how to fix*.

### Good

```
Import violation in billing/service.ts:12 — Service layer cannot import from UI layer. See kb/architecture/dependency-rules.md. Fix by extracting the type to billing/types/
```

This gives the agent the exact file, line, violation, reference doc, and a concrete
fix action.

## How to Write a New Lint Rule

1. Read `framework/lint-rule-template.md` for the full template.
2. Create a new `.sh` file under `rules/` in the appropriate subdirectory
   (e.g., `rules/kb/` for kb-related rules).
3. The script must:
   - Be executable (`chmod +x`).
   - Accept the project root as the first argument (`$1`), defaulting to the
     current working directory.
   - Exit 0 if the check passes.
   - Exit 1 if the check fails.
   - Print agent-readable messages to stdout (file:line, violation, remediation).
4. Add an entry to `.lint-config.json` with `enabled`, `severity`, and any
   rule-specific options.

## Configuring Rules

Rules are configured in `linters/.lint-config.json`:

```json
{
  "rules": {
    "kb/docs-freshness": {
      "enabled": true,
      "severity": "warning",
      "max_days_stale": 30
    },
    "kb/cross-links": {
      "enabled": true,
      "severity": "error"
    },
    "kb/plan-structure": {
      "enabled": true,
      "severity": "warning"
    }
  }
}
```

- **enabled**: `true` or `false`. Disabled rules are skipped entirely.
- **severity**: `"error"` or `"warning"`. Errors cause the lint run to fail (exit 1).
  Warnings are reported but do not fail the run.
- Additional keys are rule-specific options passed via environment variables or
  read from the config by the rule script.

## Directory Structure

```
linters/
  .lint-config.json          # Rule configuration
  README.md                  # This file
  framework/
    run-lints.sh             # Entry point — discovers and runs rules
    lint-rule-template.md    # Template for new lint rules
  rules/
    kb/
      docs-freshness.sh      # Check kb doc staleness
      cross-links.sh         # Validate markdown cross-links
      plan-structure.sh      # Validate exec plan structure
```
