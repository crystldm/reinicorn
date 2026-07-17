# Reinicorn Project Instructions

Read and follow `AGENTS.md` in this repository root. It contains all project conventions, knowledge base locations, CLI commands, and hard rules.

## Skill Invocation

This project uses Reinicorn skills in `.agents/skills/`. Use the `skill` tool to invoke them by name. Before any response or action, check if a skill applies — even a 1% chance means invoke it.

Key skills:
- `using-reinicorn` — start of every conversation in this repo
- `brainstorming` — before any creative or feature work
- `writing-plans` — before multi-step implementation
- `systematic-debugging` — before fixing any bug
- `populate-agents-md` — if AGENTS.md has UNPOPULATED marker

## Doc Creation

All kb docs must be created via the per-type commands: `rcorn spec create "title"`, `rcorn prd create "title"`, `rcorn plan create`, `rcorn retro create`, `rcorn idea create "title"`, etc. Never hand-write docs in `kb/{repo}/` protected paths.

Available types: spec, plan, prd, debt, retro, idea, principle
