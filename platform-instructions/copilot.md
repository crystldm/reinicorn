# Reinicorn Project Instructions

Read and follow `AGENTS.md` in this repository root. It contains all project conventions, knowledge base locations, CLI commands, and hard rules.

## Skill Invocation

This project uses Reinicorn skills in your skills directory (default `.agents/skills/`, configurable via `REINICORN_SKILLS_DIR`). Use the `skill` tool to invoke them by name. Before any response or action, check if a skill applies — even a 1% chance means invoke it.

Key skills:
- `using-reinicorn` — start of every conversation in this repo
- `populate-agents-md` — if AGENTS.md has UNPOPULATED marker

Process skills (brainstorming, planning, debugging, etc.) come from your
installed skill set, not this list — run `rcorn skills list` to see what's
installed. When a task matches one, invoke it before acting. Reinicorn
takes no position on methodology, only on where docs live and how they
are created.

## Doc Creation

All kb docs must be created via the per-type commands: `rcorn spec create "title"`, `rcorn prd create "title"`, `rcorn plan create`, `rcorn retro create`, `rcorn idea create "title"`, etc. Never hand-write docs in `kb/{repo}/` protected paths.

Before authoring any registered doc type, consult
`<skills-dir>/using-reinicorn/references/skillset-wiring.md` (generated —
lists every doc type, its creation command, and the skill(s) to invoke
first). Invoke the listed skill(s) before creating the doc. When a doc
type lists no skills, the creation command alone is the contract: create
the doc directly via the CLI.

Available types: spec, plan, prd, debt, retro, idea, principle
