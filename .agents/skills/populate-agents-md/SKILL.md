---
name: populate-agents-md
description: "Analyze repo and populate AGENTS.md through collaborative dialogue. Use when AGENTS.md contains the UNPOPULATED marker or when user asks to populate AGENTS.md."
---

# Populate AGENTS.md

Analyze this repository and collaboratively fill in the project-specific sections of AGENTS.md.

## When to Use

- AGENTS.md contains `<!-- UNPOPULATED` marker
- User asks to "set up AGENTS.md", "populate AGENTS.md", or similar
- SessionStart hook nudged you to run this skill

## Process

Follow a brainstorming-style dialogue. Gather information first, then ask questions, then draft.

### Step 1: Gather Context (silent)

Read these files if they exist — do NOT ask the user for them:

- `AGENTS.md` (current state)
- `CLAUDE.md`, `.cursorrules`, `AGENTS.md.bak` (existing agent config — use as baseline)
- `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Makefile` (tech stack)
- `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile` (CI)
- `README.md` (project description)
- Directory structure (`ls` top-level and `src/` or equivalent)

### Step 2: Present Findings

Tell the user what you found:

> "Here's what I found about your repo:
> - **Tech stack:** [language, framework, package manager]
> - **Build/test:** [commands detected]
> - **Structure:** [brief layout]
> - **Existing agent config:** [list any CLAUDE.md etc. found]"

### Step 3: Ask Questions (one at a time)

Ask these questions one at a time. Skip any you can confidently answer from Step 1:

1. "What does this project do in one sentence?"
2. "Any naming conventions or code patterns agents should follow?"
3. "Anything agents should avoid doing in this repo?"

### Step 4: Draft and Review

Present the filled-in AGENTS.md for user approval. Only modify the TODO/placeholder sections:

- **Project description** (the `<!-- TODO: One paragraph -->` under the title)
- **Tech Stack & Build** section
- **Project Conventions** section

**NEVER modify these pre-filled sections:**
- Knowledge Base
- CLI
- Hard Rules
- Progressive Disclosure

### Step 5: Write

After user approves:

1. Replace the TODO sections with the approved content
2. Remove the `<!-- UNPOPULATED: ... -->` marker from line 1
3. If existing CLAUDE.md was found, suggest whether to keep it alongside AGENTS.md or merge relevant content

## Handling Existing Agent Config

If CLAUDE.md or .cursorrules exist:

- **Extract useful info** (tech stack, conventions, build commands) as baseline for AGENTS.md
- **Don't delete them** — suggest to the user whether to keep both or consolidate
- **AGENTS.md is platform-agnostic** (read by Claude, Codex, Cursor)
- **CLAUDE.md is Claude-specific** — keep it for Claude-only settings if needed
