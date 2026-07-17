# CI Recovery Framework

## What This Is

The CI recovery framework provides structured instructions that agents follow to diagnose, fix, and re-trigger CI failures automatically. It is not prose documentation -- it is a set of machine-readable decision trees and handler protocols.

## How It Works

When CI fails on a branch, an agent:

1. Reads `recovery-protocol.md` for the generic decision tree.
2. Reads the relevant `platforms/` doc to learn how to fetch logs and re-trigger jobs for the CI system in use.
3. Classifies the failure and reads the matching `handlers/` doc for diagnosis and fix instructions.
4. Attempts the fix, pushes, and verifies.
5. Escalates to a human if the fix fails.

## Directory Structure

```
ci-recovery/
├── README.md                  # This file
├── recovery-protocol.md       # Generic agent decision tree for all CI failures
├── handlers/                  # Per-failure-type diagnosis and fix instructions
│   ├── lint-failure.md
│   ├── test-failure.md
│   ├── build-failure.md
│   └── deploy-failure.md
└── platforms/                 # CI platform-specific instructions
    ├── github-actions.md      # GitHub Actions: fetch logs, re-trigger, artifacts
    └── _template.md           # Template for contributing new platform integrations
```

## How Agents Use This

Agents do not read this README during CI recovery. They read it only when they need to understand the framework's structure. During an actual CI failure, agents enter at `recovery-protocol.md` and follow the decision tree from there.

**Entry point:** `recovery-protocol.md`

## Adding a New Handler

1. Copy the structure from an existing handler in `handlers/`.
2. Every handler must include these sections: **Symptoms**, **Common Causes** (ranked by likelihood), **Diagnosis Steps**, **Fix Patterns** (with concrete examples), and **When to Escalate**.
3. All instructions must be written as agent-executable steps, not human-readable prose.
4. Error messages in examples must follow the project's agent-readable error convention (see `kb/golden-principles.md`).

## Adding a New Platform

1. Copy `platforms/_template.md`.
2. Fill in every section. The template lists the required information.
3. Test that every command in the doc works on a real CI run before merging.
4. Platform docs must cover: fetching logs, re-triggering jobs, reading artifacts, and validating workflow syntax.

## Relationship to Other Kb Components

| Component | Relationship |
|-----------|-------------|
| `kb/golden-principles.md` | Handler fix patterns reference golden principles when relevant |
| `kb/tech-debt/` | Flaky/infra failures get logged as tech debt |
| `linters/framework/` | Lint failure handler references the lint framework for rule lookup |
| `.claude/skills/review-pr.md` | PR review skill may invoke recovery protocol on CI-blocked PRs |
