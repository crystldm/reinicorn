---
name: using-reinicorn
description: Use when starting any conversation - establishes how to find and use skills, requiring Skill tool invocation before ANY response including clarifying questions
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, ignore this skill.
</SUBAGENT-STOP>

<EXTREMELY-IMPORTANT>
If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill.

IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE. YOU MUST USE IT.

This is not negotiable. You cannot rationalize your way out of this.
</EXTREMELY-IMPORTANT>

## How to Access Skills

Skills live in `.agents/skills/` (with `.claude/skills` symlinked to it for Claude Code) and are loaded automatically by your platform (Claude Code, GitHub Copilot, Cursor). When a skill loads, its instructions appear in your context -- follow them directly.

- **Claude Code:** Use the `Skill` tool to invoke skills by name.
- **GitHub Copilot / Cursor:** Skills auto-load when your request matches a skill's description, or invoke via `/skill-name`.

Never use the Read tool on skill files -- always use your platform's native skill mechanism.

## The Rule

**Invoke relevant or requested skills BEFORE any response or action** — including clarifying questions, exploring the codebase, or checking files. If it turns out wrong for the situation, you don't have to use it.

Then announce "Using [skill] to [purpose]" and follow the skill exactly. If it has a checklist, create a todo per item.

## Doc-Type Wiring

Before authoring any registered doc type, consult
`references/skillset-wiring.md` (generated — lists every doc type, its
creation command, and the skill(s) to invoke first). Invoke the listed
skill(s) before creating the doc. When a doc type lists no skills — no
skill-set adapter is installed — the creation command alone is the contract:
create the doc directly via the CLI.

Process skills (debugging, planning, review) come from your installed
skill set; when a task matches one, invoke it before acting. Reinicorn
takes no position on methodology — only on where docs live and how they
are created.

## Red Flags

These thoughts mean STOP—you're rationalizing:

| Thought | Reality |
|---------|---------|
| "This is just a simple question" | Questions are tasks. Check for skills. |
| "I need more context first" | Skill check comes BEFORE clarifying questions. |
| "Let me explore the codebase first" | Skills tell you HOW to explore. Check first. |
| "I can check git/files quickly" | Files lack conversation context. Check for skills. |
| "Let me gather information first" | Skills tell you HOW to gather information. |
| "This doesn't need a formal skill" | If a skill exists, use it. |
| "I remember this skill" | Skills evolve. Read current version. |
| "This doesn't count as a task" | Action = task. Check for skills. |
| "The skill is overkill" | Simple things become complex. Use it. |
| "I'll just do this one thing first" | Check BEFORE doing anything. |
| "This feels productive" | Undisciplined action wastes time. Skills prevent this. |
| "I know what that means" | Knowing the concept ≠ using the skill. Invoke it. |

## Platform Adaptation

If your harness appears here, read its reference file for special instructions:

- Codex: `references/codex-tools.md`

## Reinicorn CLI Quick Reference

Bare `rcorn` (no args) shows a live status home view (branch, active plans,
overlap), not usage — use `rcorn help` / `rcorn --help` for the manual.

| Command | Purpose |
|---|---|
| `rcorn kb sync` | Pull latest kb state |
| `rcorn kb publish` | Push kb changes (rebase + push) |
| `rcorn kb status` | Kb health, active plans, overlap, stale docs |
| `rcorn kb status --compact` | ≤10-line dashboard for agent context (session-start hook) |
| `rcorn kb lint` | Run kb lint rules |
| `rcorn kb list` | List repo scopes in the kb |
| `rcorn kb remove-scope <name>` | Remove a repo scope |
| `rcorn kb git <args...>` | Raw git passthrough inside the kb |
| `rcorn spec create "title"` | Create a spec (implementation contract) |
| `rcorn prd create "title"` | Create a product requirements doc |
| `rcorn debt create "title"` | Create a tech-debt doc |
| `rcorn idea create "text"` | Capture an idea |
| `rcorn <spec\|prd\|debt\|idea> show <slug> [--full]` | Read a kb doc, truncated preview (`--full` for all) |
| `rcorn <spec\|prd\|debt\|idea> list` | List kb docs of that type |
| `rcorn plan create` | Create execution plan for current branch |
| `rcorn plan status` | Plan status for current branch |
| `rcorn plan show [branch] [--full]` | Show plan doc, truncated preview (`--full` for all) |
| `rcorn plan complete [branch]` | Archive plan to completed/ |
| `rcorn retro create` | Create retro for current branch |
| `rcorn retro show [branch] [--full]` | Show retro doc, truncated preview (`--full` for all) |
| `rcorn principle add "title"` | Append a golden principle |
| `rcorn mode enable` / `disable` / `incognito` / `status` | Mode toggles |
| `rcorn init [...]` | Set up Reinicorn in this repo |
| `rcorn hooks install` | Install git and editor hooks |
| `rcorn update [--diff X]` | Re-sync bundled files (skills, hooks, linters) to the installed Reinicorn version |
| `rcorn feedback [text]` | Open a GitHub issue on the Reinicorn tool repo itself (bug/idea about Reinicorn, not your project) |

## Doc Creation Rule

All kb docs MUST be created via the per-type commands shown above. Never hand-write kb docs in protected paths (`kb/{repo}/specs/`, `kb/{repo}/prds/`, `kb/{repo}/tech-debt/`, `kb/{repo}/exec-plans/`, `kb/{repo}/ideas/`).

Available types: spec, plan, prd, debt, retro, idea, principle

## Golden Principles

Before starting work, check `kb/{repo}/golden-principles.md` for project-specific rules that override general practices.

## User Instructions

User instructions (CLAUDE.md, AGENTS.md, direct requests) take precedence over skills, which in turn override default behavior. Only skip skill workflows or instructions when your human partner has explicitly told you to.
