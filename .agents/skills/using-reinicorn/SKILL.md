---
name: using-reinicorn
description: Use when starting any conversation in a Reinicorn-managed repo - explains the kb doc layer, how registered doc types map to skills via the generated wiring doc, and the rcorn CLI.
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, ignore this skill.
</SUBAGENT-STOP>

# Using Reinicorn

Reinicorn manages a knowledge base (kb) of project docs and the discipline
around them. It takes no position on methodology — how you brainstorm, plan,
debug, or review comes from whatever skill set is installed. Reinicorn owns
three things:

1. **Where docs live** — the kb, one scope per repo.
2. **How docs are created** — through `rcorn`, never by hand.
3. **Which skills gate which docs** — the wiring doc, generated from the
   doc-type registry.

## Doc-Type Wiring

Before authoring any registered doc type, consult
`references/skillset-wiring.md` (generated — lists every registered doc
type, its creation command, and the skill(s) to invoke first). Invoke the
listed skill(s) before creating the doc. When a doc type lists no skills,
the creation command alone is the contract: create the doc directly via
the CLI.

## Doc Creation Rule

Every kb doc is created with its registered command (`rcorn <type> create
...`, exact form per type in the wiring doc) — never hand-written into the
kb's protected paths. The CLI owns placement, naming, templates, and
frontmatter; hand-written docs break linting and review tooling.

## Skills

Skills live in your skills directory (default `.agents/skills/`,
configurable; `.claude/skills` is linked to it for Claude Code) and load
through your platform's native mechanism — never use the Read tool on a
skill file.

- **Claude Code:** invoke skills with the `Skill` tool.
- **GitHub Copilot / Cursor:** skills auto-load when a request matches, or
  invoke via `/skill-name`.

Invoke a relevant skill *before* responding or acting — including before
clarifying questions or codebase exploration — and announce "Using [skill]
to [purpose]". Process skills (debugging, planning, review) come from your
installed skill set; when a task matches one, it applies.

Two native skills (`using-reinicorn`, `populate-agents-md`) ship with
Reinicorn and are managed by `rcorn update`. Everything else comes from a
skill-set adapter (`rcorn skills install <name>`) and is managed by the
`rcorn skills` commands.

## Platform Adaptation

If your harness appears here, read its reference file for special
instructions:

- Codex: `references/codex-tools.md`

## Reinicorn CLI Quick Reference

Bare `rcorn` (no args) shows a live status home view (branch, active plans,
overlap), not usage — use `rcorn help` / `rcorn --help` for the manual.

| Command | Purpose |
|---|---|
| `rcorn <type> create ...` | Create a kb doc of any registered type (creation commands per type: see the wiring doc) |
| `rcorn <type> show [...] [--full]` | Read a kb doc, truncated preview (`--full` for all) |
| `rcorn <type> list` | List kb docs of that type |
| `rcorn kb sync` | Pull latest kb state |
| `rcorn kb publish` | Push kb changes (rebase + push) |
| `rcorn kb status [--compact]` | Kb health, active plans, overlap, stale docs |
| `rcorn kb lint` | Run kb lint rules |
| `rcorn kb list` | List repo scopes in the kb |
| `rcorn kb remove-scope <name>` | Remove a repo scope |
| `rcorn kb git <args...>` | Raw git passthrough inside the kb |
| `rcorn principle add "title"` | Append a golden principle |
| `rcorn skills install <name>` | Install a skill-set adapter |
| `rcorn skills status` / `list` | Installed adapter state / bundled adapters |
| `rcorn skills update [--ref X] [--force]` | Re-apply or re-pin the installed adapter |
| `rcorn mode enable` / `disable` / `incognito` / `status` | Mode toggles |
| `rcorn init [...]` | Set up Reinicorn in this repo |
| `rcorn hooks install` | Install git and editor hooks |
| `rcorn update [--diff X]` | Re-sync bundled files (native skills, hooks, linters) to the installed Reinicorn version |
| `rcorn feedback [text]` | Open a GitHub issue on the Reinicorn tool repo itself (bug/idea about Reinicorn, not your project) |

## Golden Principles

Before starting work, check `kb/{repo}/golden-principles.md` for
project-specific rules that override general practices.

## User Instructions

User instructions (CLAUDE.md, AGENTS.md, direct requests) take precedence
over skills, which in turn override default behavior. Only skip skill
workflows or instructions when your human partner has explicitly told you
to.
