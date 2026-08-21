# Reinicorn

Reinicorn is a tool and skill set for managing agentic coding workflows in
close collaboration with human developers. Inspired by OpenAI's
[Harness Engineering](https://openai.com/index/harness-engineering/) article,
Reinicorn puts the principles outlined there into practice in a simple,
straightforward way: a set of skills, hooks (both `git` and harness), and the
`rcorn` CLI, built on [AXI](https://github.com/kunchenguid/axi) principles. No
MCP, no vector database, no extra cloud storage (excuse the LLM-ism). It keeps
your docs organized and helps minimize the slop.

At the core of Reinicorn is a spec-driven-development workflow and a
knowledgebase repository for keeping track of the `.md` files you generate.
The methodology skills that drive that workflow are pluggable: install the
bundled adapter for [obra/superpowers](https://github.com/obra/superpowers)
or bring your own (see [The skill set](#the-skill-set)). Every document comes
from a template, so provenance and review status are first-class rather than
something you remember to add.

Specs get placed in `kb/<project-slug>/specs/drafts` and can then be put up for
review. Organized metadata keeps track of all the details. When the review PR
passes, the spec can be distilled into implementation plans. The code is
reviewed as normal, of course, but having the team collaborate on and validate
the intent first saves a lot of time and effort.

The knowledgebase lives as a separate repository, always on its `main` branch
except for single-doc review PRs. One `kb` can be shared across multiple
repositories, so all domain knowledge sits in one place, accessible to every
agent across a multi-repo, multi-team project.

The core loop works: spec → review → implementation → test → retro is (mostly)
there. Plenty is still missing, and many ideas are open for implementation in
the [knowledgebase](https://github.com/crystldm/reinicorn-kb). Contribution,
testing, and feedback are most welcome: `rcorn feedback` opens an issue on
this repo. I've dog-fooded the project from day one (I built Reinicorn using
Reinicorn), but the next test is real team workflows.

The CLI's output follows the
[axi principles](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/agent-native-output-surface-axi-principles.md)
("agent experience"): output designed to be read by agents and humans alike.
If you plan to modify the CLI, read that spec first.

## Quick Start

You need git 2.34+, Python 3.12+, and [uv](https://docs.astral.sh/uv/).
reinicorn is not yet on PyPI, so install straight from git:

```bash
uv tool install git+https://github.com/crystldm/reinicorn.git
```

Then set up the repo you want to work in:

```bash
cd your-repo
rcorn init
```

`init` asks where the shared kb should live: an existing remote your team
already shares, a new private GitHub repo (`--create-remote`, uses the `gh`
CLI), or a local bare repo for solo experiments (`--local`). It then clones the
kb, installs the git and editor hooks, and lays down the skills and agent
instructions for your platforms.

The daily loop after that is two commands around your normal work:

```bash
rcorn kb sync      # start of day: pull the latest shared kb state
# ... work the skills: brainstorm → spec → plan → execute → retro ...
rcorn kb publish   # push your kb changes back
```

[GETTING-STARTED.md](GETTING-STARTED.md) is the fuller walkthrough, including
populating `AGENTS.md` on first run and troubleshooting.

## Repository structure

```
reinicorn/
├── AGENTS.md               # Universal agent entry point (sparse map)
├── GETTING-STARTED.md      # Setup and troubleshooting walkthrough
├── src/reinicorn/          # The CLI: commands, kb/git plumbing, linter, doc-type registry
├── .agents/skills/         # Canonical skill set (.claude/skills symlinks here)
├── hooks/                  # Git hooks: post-checkout, post-merge, pre-push
├── editor-hooks/           # Editor guard hooks: doc-template + raw-kb-git guards
├── linters/                # Stack-agnostic kb lint framework and rules
├── platform-instructions/  # Per-platform pointer files (claude, cursor, copilot)
├── templates/              # AGENTS.md template laid down by init
├── workflows/              # CI workflow installed by `rcorn review setup`
├── upgrades/               # Version-to-version upgrade notes
├── kb/                     # The shared knowledgebase (gitignored clone)
└── tests/                  # Test suite
```

## The workflow

Everything here follows from the harness engineering article's central claim:
the repository is the source of truth. If context lives in a chat thread or in
someone's head, agents can't see it. The kb is where it becomes visible to the
whole team, including agents working on other branches. The workflow exists to
get the important context written down, and to make sure it can be trusted
once it is. The full set of beliefs behind the design is in
[core-beliefs.md](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/core-beliefs.md);
several of them come up below.

Work starts with a **spec**, the implementation contract: problem, design
goals, design, non-goals. Specs come from wherever work comes from: a PRD, a
roadmap conversation, a bug that exposed a design flaw, an idea captured weeks
earlier. With the superpowers adapter installed (see [The skill
set](#the-skill-set)), the brainstorming skill turns that raw intent into a
design through dialogue; `rcorn spec create` turns the design into a draft in
the kb either way. A draft only becomes authoritative after doc review (next
section).

With a spec in hand, work moves to a feature branch. `rcorn plan create`
scaffolds an execution plan scoped to that branch (goal, acceptance criteria,
tasks) and publishes it to the kb. Because every branch's plan is visible in
one place, `rcorn kb status` can compare active branches and flag overlap
before two people silently rewrite the same file. This is what the article
calls cross-branch awareness. With the superpowers adapter installed, the
executing-plans skill works the plan step by step; when the branch merges,
`rcorn plan complete` archives it and asks for a retro, because lessons that
never get written down are lost.

Two capture commands sit outside the main loop. `rcorn idea create` is for
the thought that strikes while you're doing something else: file it and stay
on task, instead of losing it or chasing it. `rcorn debt create` catalogs tech
debt as you encounter it. Debt compounds fast in agent-assisted codebases,
since a shortcut taken today becomes a pattern agents replicate tomorrow.

The other belief doing heavy lifting here is mechanical enforcement over
documented conventions: a rule that exists only in prose will eventually be
violated, so wherever possible the rules are code. Every document is created
from a template through the CLI. The protected kb paths (`specs/`, `prds/`,
`tech-debt/`, `exec-plans/`, `ideas/`) reject direct writes, so a doc can't
exist without its provenance fields and required sections. `rcorn kb lint`
checks cross-links, doc freshness, plan structure, and drafts referenced as if
they were approved. Team taste gets the same treatment: `rcorn principle add`
appends to the repo's golden principles, capturing a human preference once so
it can be enforced continuously instead of re-litigated in every review.

The document types, each with its template and protected location:

| Type | Create command | What it is |
|------|----------------|------------|
| spec | `rcorn spec create "<title>"` | The implementation contract: problem, design goals, design, non-goals |
| prd | `rcorn prd create "<title>"` | Product requirements: overview, user stories, acceptance criteria, out of scope |
| plan | `rcorn plan create` | Per-branch execution plan: goal, acceptance criteria, tasks |
| retro | `rcorn retro create` | Per-branch retrospective: what went well, what to improve, lessons, actions |
| debt | `rcorn debt create "<title>"` | Tech-debt entry: impact and remediation plan |
| idea | `rcorn idea create "<idea>"` | Quick capture, filed by author |
| principle | `rcorn principle add "<title>"` | Appends a golden principle to the repo's ruleset |

### Doc review

Specs shape everything built after them, so they get the same review treatment
as code. The process stays lightweight, though: corrections are cheap and
waiting is expensive. `rcorn spec create` writes the draft to `specs/drafts/`
on kb main, visible to everyone immediately but excluded from
`rcorn spec list` and `show` unless you ask for drafts. When it's ready:

```bash
rcorn review start <slug>     # push a review branch, open a PR, request reviewers
rcorn review push <slug>      # sync later edits into the PR
rcorn review merge <slug>     # merge the approved PR, land the doc, delete the draft
rcorn review status           # open reviews in this repo scope
```

The kb checkout never leaves `main`. The review branch exists only on the
remote, so reviewers get a full-file GitHub diff with inline comments while
your working copy stays put. Merging (from the CLI or the GitHub UI) flips the
draft to `approved` at its canonical `specs/<slug>.md` path, and `rcorn review
setup` installs a small CI workflow so a browser merge finishes the cleanup on
its own. `gh` is optional at every step; without it, reinicorn pushes the
branch and hands you the PR link to open yourself. `rcorn kb lint` warns when
a plan builds on a spec that never got approved.

## The CLI

`rcorn` is the single entry point for kb operations; it hides the git plumbing
so neither humans nor agents touch the kb clone directly. Bare `rcorn` shows
a live status home view (branch, active plans, overlap), and `rcorn help` has
the full manual.

The [axi spec](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/agent-native-output-surface-axi-principles.md)
sets the output rules: content first, structured errors on stdout where agents
can see them, and a `next:` footer suggesting the likely next command. Tests
enforce these rules, so read the spec before changing how any command talks.

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
| `rcorn <spec\|prd\|debt\|idea> create "..."` | Create a doc of that type from its template |
| `rcorn <spec\|prd\|debt\|idea> show <slug> [--full]` | Read a kb doc (truncated preview by default) |
| `rcorn <spec\|prd\|debt\|idea> list` | List kb docs of that type |
| `rcorn plan create` | Create execution plan for current branch |
| `rcorn plan status` | Plan status for current branch |
| `rcorn plan show [branch] [--full]` | Show plan doc |
| `rcorn plan complete [branch]` | Archive plan to completed/ |
| `rcorn retro create` | Create retro for current branch |
| `rcorn retro show [branch] [--full]` | Show retro doc |
| `rcorn review start\|push\|merge\|cancel\|link\|status` | The doc-review lane (see above) |
| `rcorn review setup` | Install kb-repo CI cleanup workflow + ruleset |
| `rcorn principle add "title"` | Append a golden principle |
| `rcorn skills install [<name>]` | Install a skill-set adapter; no name restores the one the lockfile records |
| `rcorn skills status` / `list` | Installed adapter state / bundled adapters |
| `rcorn skills update [--ref X] [--force]` | Re-apply or re-pin the installed adapter |
| `rcorn mode enable\|disable\|incognito\|status` | Mode toggles |
| `rcorn init [...]` | Set up reinicorn in this repo |
| `rcorn hooks install` | Install git and editor hooks |
| `rcorn update [--diff X]` | Re-sync bundled files (skills, hooks, linters) to the installed version |
| `rcorn feedback [text]` | Open a GitHub issue on the reinicorn repo itself |

## The skill set

Skills live in `.agents/skills/` (the Agent Skills open standard) and load
automatically on Claude Code, Cursor, GitHub Copilot, and Codex. Reinicorn
ships two native skills and takes no position on development methodology
beyond them:

- `using-reinicorn`: how to find and use skills; loads first, every session
- `populate-agents-md`: fill in `AGENTS.md` through guided dialogue

Methodology (brainstorming, planning, TDD, code review, worktrees, and so on)
comes from a **skill-set adapter** you install:

```bash
rcorn skills install superpowers
```

This fetches a pinned, kb-compatible build of
[obra/superpowers](https://github.com/obra/superpowers) — brainstorming,
writing-plans, executing-plans, test-driven-development,
systematic-debugging, and the rest of that pack — patched to write docs
through `rcorn` instead of its own conventions. `rcorn skills list` shows
bundled adapters, and `rcorn skills status` reports what's installed. You can
also point `rcorn skills install` at your own adapter definition to wire up
a house skill set.

An install records what it did in `.reinicorn/skillset-lock.json` — the
adapter, its pinned commit, and a hash of every file it wrote. **Commit the
lockfile.** It is the project's declared methodology, the same way
`uv.lock` declares its dependencies; the installed skill files themselves
can be committed or gitignored (this repo gitignores them). A fresh clone or
new worktree that has the lock but not the files gets them back
automatically — `rcorn update`, `rcorn init`, and the post-checkout hook
all restore from the lock, and `rcorn skills install` with no argument does
it on demand. Restore writes only what is missing and never touches a file
that exists.

Whichever skill set (if any) is installed, `using-reinicorn`'s generated
wiring doc
([`.agents/skills/using-reinicorn/references/skillset-wiring.md`](.agents/skills/using-reinicorn/references/skillset-wiring.md))
maps every doc type to its creation command and the skill(s) to invoke first;
with no adapter installed, the creation commands alone are the contract.

## KB as a shared clone

The kb is an ordinary git clone at `kb/`, gitignored in every repo that
attaches it, tracking a shared repo on `main` only (linear history, no
branches). Every branch and contributor reads and writes the same kb, which
is what makes cross-branch context and overlap detection possible. On a
fresh checkout of your repo, `rcorn kb sync` bootstraps `kb/` from scratch —
there's no pointer to check out, so nothing to forget to init.

The clone design is also what enables multi-repo support, unchanged from
before. Several repos can attach the same kb repo, and each gets its own
top-level scope directory named after its repo slug (`kb/reinicorn/`,
`kb/my-service/`). All doc types live inside that scope, so projects sharing
one kb never collide, while agents working in any repo can see the others'
context. `rcorn init` is additive (safe to run against a kb that already
holds other repos' scopes), and `rcorn kb list` / `rcorn kb remove-scope
<name>` manage the scopes.

As promised in the intro, nobody manages the kb checkout by hand:

- `rcorn kb sync` clones `kb/` if it's missing, pulls the latest kb state, and
  reports overlap.
- `rcorn kb publish` rebases and pushes your changes. Namespaced files (your
  branch's plan) auto-resolve in your favor; shared-file conflicts are skipped
  with a warning so you stay unblocked.
- `kb/` is gitignored, so there's no pointer commit to keep honest. A local
  pre-commit hook blocks staging it by accident; CI is the actual backstop —
  it fails the build if `kb/` is ever tracked, which is the layer a
  contributor can't route around.

Two escape hatches for when the workflow is in your way:

- `rcorn mode incognito`: read-only. Keep syncing and seeing others' work,
  but never publish your own.
- `rcorn mode disable`: turn hooks and background operations off entirely
  until you re-enable.

## Contributing

reinicorn is shaped by real usage, so feedback on what helps and what gets in
the way is the most valuable contribution. File it with `rcorn feedback "..."`
or open an issue directly. Code and docs contributions are welcome too: see
[CONTRIBUTING.md](CONTRIBUTING.md).

## References

- [OpenAI: Harness Engineering](https://openai.com/index/harness-engineering/): the article that inspired the project.
- [obra/superpowers](https://github.com/obra/superpowers): the upstream for the bundled `superpowers` skill-set adapter.
- [core-beliefs.md](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/core-beliefs.md): the operating principles, adapted from the article for this project.
- [axi principles](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/agent-native-output-surface-axi-principles.md): the agent-experience rules the CLI's output follows.
- [Remove the kb submodule](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/remove-the-kb-submodule.md): why the kb is a plain clone instead of a git submodule.

## License

MIT.
