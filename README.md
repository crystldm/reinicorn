# reinicorn

**reinicorn** is a skill set and CLI for running spec-driven development with AI
coding agents. Humans steer, agents execute: the knowledgebase (`kb/`, a git
submodule shared across every branch and contributor) encodes intent,
constraints, and context, while hooks and the `reinicorn` CLI keep that context
honest — design docs can only be created through the CLI, protected kb paths
stay protected, and overlapping work across branches surfaces before it
collides. It runs on Claude Code, Cursor, GitHub Copilot, and Codex from one
set of skills and one universal entry point.

For a hand-written intro from the author on why this exists, see
[HUMANS.md](HUMANS.md).

## Status

Beta candidate. The core works, but the surface is still settling — command
names, kb layout, and skill boundaries may shift before 1.0. If something is
rough or wrong, tell us: `rcorn feedback "<what happened>"` opens an issue on
the reinicorn repo directly.

## Quick start

```bash
# not yet on PyPI — install straight from git:
uv tool install git+https://github.com/crystldm/reinicorn.git

# then, in the repo you want to set up:
cd your-repo && rcorn init
```

`rcorn init` detects your context (existing repo or fresh directory), wires up
the kb submodule, installs git and editor hooks, and lays down the skills and
agent instructions for whichever platforms you use.

Then the daily loop:

```bash
rcorn kb sync                # pull the latest shared kb state
# ... work the skills: brainstorming → spec → plan → execute → retro ...
rcorn kb publish             # rebase + push your kb changes back
```

## The workflow

reinicorn enforces spec-driven development rather than merely suggesting it. The
protected kb paths (`specs/`, `prds/`, `tech-debt/`, `exec-plans/`, `ideas/`)
reject direct edits — every design doc has to be created through
`reinicorn <type> create`, so a plan or spec exists as a real artifact before code
does. Each branch gets its own execution plan. When you finish, a retro is
expected: `rcorn plan complete` warns if no retro was captured, because lessons
learned that never get written down are lost. Golden principles capture the
project's non-negotiable rules (and are lintable where possible), and overlap
detection compares what each active branch has touched so two people don't
silently rewrite the same file.

Documents are created by type, each from a template, each landing in a
protected location:

| Type | Create command | What it is |
|------|----------------|------------|
| spec | `rcorn spec create "<title>"` | The implementation contract: problem, design goals, design, non-goals |
| prd | `rcorn prd create "<title>"` | Product requirements: overview, user stories, acceptance criteria, out of scope |
| plan | `rcorn plan create` | Per-branch execution plan: goal, acceptance criteria, tasks |
| retro | `rcorn retro create` | Per-branch retrospective at finish: what went well, what to improve, lessons, actions |
| debt | `rcorn debt create "<title>"` | Tech-debt entry: impact and remediation plan |
| idea | `rcorn idea create "<idea>"` | Quick capture, filed by author |
| principle | `rcorn principle add "<title>"` | Appends a golden principle to the repo's ruleset |

### Doc review

Gated doc types (currently `spec`) go through PR-style review before they count
as authoritative — the same rigor code gets. `rcorn spec create` writes the
draft to `specs/drafts/` on kb main (visible to everyone, but excluded from
`rcorn spec list`/`show` unless you pass `--include-drafts`). When it's ready:

```bash
rcorn review start <slug>     # push a review branch, open a PR, request reviewers
rcorn review push <slug>      # sync later edits into the PR
rcorn review merge <slug>     # merge the approved PR, land the doc, delete the draft
rcorn review status           # open reviews in this repo scope
```

The kb checkout never leaves `main` — the review branch lives only on the
remote, so reviewers get a full-file GitHub diff with inline comments while your
working copy stays on main. Merging (from the CLI or the GitHub UI) flips the
draft to `approved` at its canonical `specs/<slug>.md` path; `rcorn review
setup` installs a CI workflow so a browser merge finishes the cleanup on its
own. `gh` is optional at every step — without it, reinicorn pushes the branch and
hands you the PR link to open manually. `rcorn kb lint` warns when a plan builds
on an unapproved draft.

## The CLI

`reinicorn` is the single entry point for kb operations; it hides the git plumbing
so neither humans nor agents touch the submodule directly. Bare `reinicorn` shows a
live status home view (branch, active plans, overlap) — run `rcorn help` for
the full manual.

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
| `reinicorn <spec\|prd\|debt\|idea> show <slug> [--full]` | Read a kb doc, truncated preview (`--full` for all) |
| `reinicorn <spec\|prd\|debt\|idea> list` | List kb docs of that type |
| `rcorn plan create` | Create execution plan for current branch |
| `rcorn plan status` | Plan status for current branch |
| `rcorn plan show [branch] [--full]` | Show plan doc, truncated preview (`--full` for all) |
| `rcorn plan complete [branch]` | Archive plan to completed/ |
| `rcorn retro create` | Create retro for current branch |
| `rcorn retro show [branch] [--full]` | Show retro doc, truncated preview (`--full` for all) |
| `rcorn review start <slug>` | Open a PR-style review for a draft spec |
| `rcorn review push <slug>` | Sync draft edits into the open review PR |
| `rcorn review merge <slug>` | Merge an approved review, land the doc |
| `rcorn review cancel <slug>` | Close a review, keep the draft |
| `rcorn review status` | List open reviews in this repo scope |
| `rcorn review setup` | Install kb-repo CI cleanup workflow + ruleset |
| `rcorn principle add "title"` | Append a golden principle |
| `rcorn mode enable` / `disable` / `incognito` / `status` | Mode toggles |
| `rcorn init [...]` | Set up reinicorn in this repo |
| `rcorn hooks install` | Install git and editor hooks |
| `rcorn update [--diff X]` | Re-sync bundled files (skills, hooks, AGENTS.md) to the installed version |
| `rcorn feedback [text]` | Open a GitHub issue on the reinicorn tool repo itself |

## The skill set

Skills live in `.agents/skills/` and load automatically on whatever platform
you run.

**Workflow**

- `using-reinicorn` — how to find and use skills; loads first, every session
- `brainstorming` — explore intent and requirements before any creative work
- `writing-plans` — turn a spec into a step-by-step implementation plan
- `executing-plans` — work a written plan with review checkpoints
- `subagent-driven-development` — execute independent plan tasks via subagents
- `finishing-a-development-branch` — structured merge / PR / cleanup at the end

**Discipline**

- `test-driven-development` — tests before implementation, no exceptions
- `systematic-debugging` — root-cause a bug before proposing a fix
- `verification-before-completion` — evidence before you claim something works
- `requesting-code-review` — get work reviewed before merging
- `receiving-code-review` — respond to review with rigor, not reflexive agreement

**Supporting**

- `using-git-worktrees` — isolate feature work in a worktree
- `dispatching-parallel-agents` — fan out 2+ independent tasks
- `populate-agents-md` — fill in `AGENTS.md` through guided dialogue
- `writing-skills` — author and verify new skills
- `update-superpowers` — pull forked skills forward from upstream

Several skills are forked from the [superpowers](https://github.com/obra/superpowers)
Claude Code plugin; attribution, versions, and the upstream MIT license text are
in [.agents/skills/ATTRIBUTION.md](.agents/skills/ATTRIBUTION.md).

## Platforms

reinicorn targets Claude Code, Cursor, GitHub Copilot, and Codex from a single
source. `AGENTS.md` is the universal entry point every agent reads first. Skills
live canonically in `.agents/skills/` (the Agent Skills open standard, which
Cursor, Copilot, and Codex read natively), with `.claude/skills` symlinked to it
for Claude Code. Each platform also gets a thin instruction file pointing back
at `AGENTS.md`.

The editor guard hooks — a doc-template guard that blocks direct writes to
protected kb paths, and a raw-kb-git guard that blocks bare `git` inside the kb
submodule — install for all three hook-capable editors (Claude Code, Cursor,
Copilot). Codex reads `AGENTS.md` and the skills directly.

## Repository structure

```
reinicorn/
├── AGENTS.md               # Universal agent entry point (sparse map)
├── pyproject.toml          # Package + build config
├── src/reinicorn/              # The CLI: commands, kb/git plumbing, linter, doc_types registry
├── .agents/skills/         # Canonical skills (.claude/skills symlinks here)
├── hooks/                  # Git hooks: post-checkout, post-merge, pre-push
├── editor-hooks/           # Editor guard hooks: doc-template + raw-kb-git guards
├── linters/                # Stack-agnostic kb lint framework, rules, CI-recovery
├── platform-instructions/  # Per-platform pointer files (claude, cursor, copilot)
├── upgrades/               # Version-to-version upgrade notes
├── kb/                     # The shared knowledgebase (git submodule)
└── tests/                  # Test suite
```

## Kb as a submodule

The kb is a git submodule pointing at a shared repo tracked on `main` only
(linear history, no branches). Every branch and contributor reads and writes the
same kb, which is what makes cross-branch context and overlap detection possible.

The submodule design is also what enables **multi-repo support** — a big
motivation for keeping the kb as a submodule rather than a plain directory.
Several repos can attach the same kb repo, and each gets its own top-level
scope directory named after its repo slug (e.g. `kb/reinicorn/`, `kb/my-service/`).
All doc types live inside that scope, so projects sharing one kb never collide,
while agents working in any repo can see the others' context. `rcorn init` is
additive — safe to run against a kb that already holds other repos' scopes —
and `rcorn kb list` / `rcorn kb remove-scope <name>` manage the scopes.

- `rcorn kb sync` pulls the latest kb state and reports overlap.
- `rcorn kb publish` rebases and pushes your changes. Namespaced files (your
  branch's plan) auto-resolve in your favor; shared-file conflicts are skipped
  with a warning so you stay unblocked.

Two escape hatches when the workflow is in your way:

- `rcorn mode incognito` — read-only: keep syncing and seeing others' work, but
  never publish your own.
- `rcorn mode disable` — turn hooks and background operations off entirely until
  you re-enable.

## Contributing

reinicorn is shaped by real usage — feedback on what helps and what gets in the way
is the most valuable contribution. File it with `rcorn feedback "..."` or open
an issue. For the fuller setup and troubleshooting walkthrough, see
[GETTING-STARTED.md](GETTING-STARTED.md).

## References

- [OpenAI: Harness Engineering](https://openai.com/index/harness-engineering/) — the idea that inspired this project.

## License

MIT.
