# Reinicorn

Reinicorn is a layer for governance of agent-assisted development and the
documents it produces. It's geared towards teams of real humans working on
projects that still require a lot of human review. (This intro is, by the way,
human-generated.) Coding with AI agents usually means creating a lot of
Markdown files: specs, plans, research results, task trackers, etc. With
Reinicorn, a repository can enforce a single workflow with fully configurable
document types and SDD skill set adapters. Instead of every team member
running their own workflow and keeping their documents in ignored local
directories, Reinicorn gives everyone a single place, managed in git. Specs,
plans, and the rest get shared across branches, SDLC phases, and repository
groups.

Inspired by OpenAI's
[Harness Engineering](https://openai.com/index/harness-engineering/) article,
Reinicorn puts the principles outlined there into practice in a simple,
straightforward way: a set of skills, hooks (both `git` and harness), and the
`rcorn` CLI, built on [AXI](https://github.com/kunchenguid/axi) principles. No
MCP, no vector database, no extra cloud storage (excuse the LLM-ism). It keeps
your docs organized, your agents in line, and helps minimize the slop.

Reinicorn is opinionated about three things and leaves the rest alone:

1. Where docs live. The knowledgebase (`kb/`) is a plain git clone shared by
   every branch, every contributor, and every repo that attaches it, with one
   scope directory per repo.
2. How docs get created. Through `rcorn`, from a registered template, never by
   hand. Provenance and review status are in the frontmatter from the start
   instead of being something you remember to add later.
3. Which skills gate which docs. Methodology (brainstorming, planning, TDD,
   debugging, code review) comes from a skill-set adapter you install, and a
   generated wiring doc tells agents which skill to run before creating each
   doc type.

The basics work. Plenty is still missing, and many ideas are open for
implementation in the
[knowledgebase](https://github.com/crystldm/reinicorn-kb). Contribution,
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
CLI), or a local bare repo for solo experiments (`--local`). It then clones
the kb, installs the git and editor hooks, and lays down the native skills and
agent instructions for your platforms. That gets you the kb and the rules. For
the methodology skills, install an adapter (see
[The skill set](#the-skill-set)):

```bash
rcorn skills install superpowers
```

The daily loop after that is two commands around your normal work:

```bash
rcorn kb sync      # start of day: pull the latest shared kb state
# ... work: rcorn spec create, rcorn plan create, rcorn idea create, ...
rcorn kb publish   # push your kb changes back
```

[GETTING-STARTED.md](GETTING-STARTED.md) is the fuller walkthrough, including
populating `AGENTS.md` on first run and troubleshooting.

## Repository structure

```
reinicorn/
├── AGENTS.md               # Universal agent entry point (sparse map)
├── GETTING-STARTED.md      # Setup and troubleshooting walkthrough
├── src/reinicorn/          # The CLI: commands, kb/git plumbing, linter, doc-type registry, skillset engine
├── adapters/               # Bundled skill-set adapter definitions (superpowers, mattpocock-skills)
├── .agents/skills/         # Native skills (.claude/skills symlinks here); adapter skills install here, gitignored
├── hooks/                  # Git hooks: pre-commit, post-checkout, post-merge, pre-push
├── editor-hooks/           # Editor guard hooks: doc-template + raw-kb-git guards
├── linters/                # Stack-agnostic kb lint framework and rules
├── platform-instructions/  # Per-platform pointer files (claude, cursor, copilot)
├── templates/              # AGENTS.md template laid down by init
├── workflows/              # kb-repo CI workflows installed by `rcorn review setup`
├── upgrades/               # Version-to-version upgrade notes
├── kb/                     # The shared knowledgebase (gitignored clone)
└── tests/                  # Test suite
```

## Doc governance

Anyone who has worked with agents for more than a week knows the pile: plans
in `docs/`, half a design in a chat thread, a decision buried in a PR
description, three versions of the same spec in somebody's local scratch
directory, etc. Nobody on the team can tell a draft from a decision anymore,
and the agents certainly can't. The harness engineering article's central
claim is that the repository is the source of truth, and everything here
follows from that. If context lives in a chat thread or in someone's head,
agents can't see it. The kb is where it becomes visible to the whole team,
including the agents working on other branches. The other belief doing a lot
of the work is mechanical enforcement over documented conventions. A rule that
only exists in prose will eventually get broken, usually by an agent that
never read it, so wherever possible the rules are code. The full set of
beliefs behind the design is in
[core-beliefs.md](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/core-beliefs.md).

### Doc types come from a registry

Every kind of document Reinicorn manages is one row in a registry, and that
row is the definition: its directory in the kb, its filename pattern, its
template and required sections, whether it is protected, whether it is
review-gated, and how it is addressed (by slug, by branch, or as a singleton).
The `rcorn <type> create|show|list` commands, the linter's section checks, the
editor guards, and the skill wiring doc are all generated from those rows.
Adding or renaming a doc type means editing the registry, not sweeping the
codebase. Two types still carry logic the row can't express: `rcorn plan
create` runs its own lifecycle code on top of the registry, and principles
append to one shared file instead of creating a new one. Everything else is
the row.

The document types that ship today:

| Type | Create command | What it is |
|------|----------------|------------|
| spec | `rcorn spec create "<title>"` | The implementation contract: problem, design goals, design, non-goals. Review-gated. |
| prd | `rcorn prd create "<title>"` | Product requirements: overview, user stories, acceptance criteria, out of scope |
| plan | `rcorn plan create` | Per-branch execution plan: goal, acceptance criteria, tasks |
| retro | `rcorn retro create` | Per-branch retrospective: what went well, what to improve, lessons, actions |
| debt | `rcorn debt create "<title>"` | Tech-debt entry: impact and remediation plan |
| idea | `rcorn idea create "<text>"` | Quick capture, filed by author |
| principle | `rcorn principle add "<title>"` | Appends a golden principle to the repo's ruleset |

### Every doc goes through the CLI

`rcorn <type> create` writes the frontmatter (type, slug, lifecycle, status,
author, origin, `human_validated`) and the required sections from the
template. The protected kb paths (`specs/`, `prds/`, `tech-debt/`,
`exec-plans/`, `ideas/`) reject direct writes through editor hooks on Claude
Code, Cursor, and Copilot, so a doc can't exist without its provenance fields.
`rcorn kb git` is the only sanctioned way to touch the clone's git state. The
hooks don't care which skill set is installed: a methodology that likes to
write `docs/plans/whatever.md` still ends up going through `rcorn plan
create`.

Plans are the one type bound to a branch rather than a slug. `rcorn plan
create` scaffolds the plan for the current branch and publishes it to the kb.
Because every branch's plan is visible in one place, `rcorn kb status` can
compare active branches and flag overlap before two people silently rewrite
the same file (the article calls this cross-branch awareness). When the branch
merges, `rcorn plan complete` archives the plan and asks for a retro.

Two capture types sit outside any workflow. `rcorn idea create` is for the
thought that strikes while you're doing something else: file it and stay on
task. `rcorn debt create` catalogs tech debt as you find it. Debt compounds
fast in agent-assisted codebases, since a shortcut taken today becomes a
pattern the agents copy tomorrow.

### The linter checks what templates can't

`rcorn kb lint` runs the rules in `linters/`: frontmatter is valid,
cross-links resolve, index files are fresh, plans have their required
structure, and no plan builds on a doc that is still a draft. Team taste gets
the same treatment: `rcorn principle add` appends to the repo's golden
principles, so a human preference gets captured once and enforced
continuously instead of re-litigated in every review. Principles are meant to
be mechanical. If you can't imagine a lint rule for one, it's a convention,
not a principle.

### Review gates

Any doc type can be review-gated; it's a flag on the registry row, so each
project decides which types get one. Specs ship gated, since a spec shapes
everything built after it and deserves the same review treatment as code: a
PR, reviewers, inline comments. Ideas and debt don't. The process is
deliberately light. Corrections at the draft stage are cheap, and making
people wait around for approval is not. Creating a gated doc writes the draft
to the type's `drafts/` directory on kb main, so the team can see it right
away, but it stays out of `list` and `show` unless you ask for drafts. When
it's ready:

```bash
rcorn review start <slug>     # push a review branch, open a PR, request reviewers
rcorn review push <slug>      # sync later edits into the PR
rcorn review merge <slug>     # merge the approved PR, land the doc, delete the draft
rcorn review status           # open reviews in this repo scope
```

The kb checkout never leaves `main`. The review branch exists only on the
remote, so reviewers get a full-file GitHub diff with inline comments while
your working copy stays put. Merging (from the CLI or the GitHub UI) flips the
draft to `approved` at its canonical path, `specs/<slug>.md` for a spec.

`rcorn review setup` installs two small CI workflows in the kb repo. One
finishes the cleanup on its own after a browser merge. The other puts two real
status checks on every kb PR: **Doc lint** (`rcorn kb lint` against the PR)
and **Candidate integrity** (the PR adds exactly its one doc, still in sync
with the draft on main). The `reinicorn-doc-review` ruleset requires both
before a merge into kb main; direct `rcorn kb publish` pushes are unaffected.
Rerun `rcorn review setup --force` after upgrading to pick up new workflow
versions. `gh` is optional at every step; without it, reinicorn pushes the
branch and hands you the PR link to open yourself.

## The CLI

`rcorn` is the one entry point for everything that touches the kb. It hides
the git plumbing so that neither humans nor agents work on the kb clone
directly. Bare `rcorn` shows a live status home view (branch, active plans,
overlap), and `rcorn help` has the full manual.

The output follows the
[axi spec](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/agent-native-output-surface-axi-principles.md):
content first, structured errors on stdout where agents can actually see them,
and a `next:` footer suggesting the likely next command. Humans and agents read
the same output, and the tests hold every command to it, so read the spec
before changing how any command talks.

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
| `rcorn review setup [--force]` | Install kb-repo CI workflows (cleanup + status checks) and the ruleset |
| `rcorn principle add "title"` | Append a golden principle |
| `rcorn skills install <name\|path>` | Install a skill-set adapter (bundled name or local directory) |
| `rcorn skills status` / `list` | Installed adapter state / bundled adapters |
| `rcorn skills update [--ref X] [--force]` | Re-apply or re-pin the installed adapter |
| `rcorn mode enable\|disable\|incognito\|status` | Mode toggles |
| `rcorn init [...]` | Set up reinicorn in this repo |
| `rcorn hooks install` | Install git and editor hooks |
| `rcorn update [--diff X]` | Re-sync bundled files (native skills, hooks, linters) to the installed version |
| `rcorn feedback [text]` | Open a GitHub issue on the reinicorn repo itself |

## The skill set

Skills live in `.agents/skills/` by default (the Agent Skills open standard;
the directory is configurable through the `REINICORN_SKILLS_DIR` repo config
key) and load automatically on Claude Code, Cursor, GitHub Copilot, and Codex.
Reinicorn ships exactly two of its own, managed by `rcorn update`:

- `using-reinicorn`: the doc contract (where docs live, the creation rule, and
  the wiring doc); loads first, every session
- `populate-agents-md`: fill in `AGENTS.md` through guided dialogue

That is the whole native opinion, on purpose. Every team already has feelings
about how to brainstorm, plan, do TDD, debug, review code, use worktrees, etc.,
and Reinicorn has no business picking for them. Methodology comes from a
**skill-set adapter** you install:

```bash
rcorn skills install <name>
```

An adapter is a declarative definition (`adapters/<name>/adapter.yaml`): an
upstream repo pinned to a commit, an explicit list of skills to take, git
patches plus append blocks that make those skills kb-compatible (write docs
through `rcorn`, respect protected paths), and a wiring map from doc types to
the skills that should run before creating them. Same adapter plus same pin
gives byte-identical output, and a patch that no longer applies fails the
install loudly instead of landing halfway. This repo contains no forked
third-party skill text, only the adapter definitions. Adapter-installed skills
are gitignored in your project, with a lockfile at
`.reinicorn/skillset-lock.json` tracking the pin and per-file hashes.

Two adapters are bundled:

- `superpowers`: [obra/superpowers](https://github.com/obra/superpowers):
  brainstorming, writing-plans, executing-plans, test-driven-development,
  systematic-debugging, and the rest of that pack.
- `mattpocock-skills`: [mattpocock/skills](https://github.com/mattpocock/skills):
  grill-with-docs, to-spec, to-tickets, wayfinder, implement, tdd,
  code-review, and the rest of the engineering pack.

`rcorn skills list` shows the bundled adapters, `rcorn skills status` reports
what's installed and whether you've edited it locally, and `rcorn skills
update` re-applies or re-pins. `rcorn skills install ./path/to/adapter` wires
up a house skill set the same way.

Whichever skill set (if any) is installed, the generated wiring doc at
`<skills-dir>/using-reinicorn/references/skillset-wiring.md`
([here](.agents/skills/using-reinicorn/references/skillset-wiring.md) in this
repo) maps every registered doc type to its creation command and the skill(s)
to invoke first. With no adapter installed, the creation commands alone are
the contract; the kb, the templates, the hooks, and the linter all work
standalone.

## KB as a shared clone

The kb is an ordinary git clone sitting at `kb/`, gitignored in every repo
that attaches it, and tracking a shared repo on `main` only (linear history,
no branches). Everyone on the team, on every branch, reads and writes the same
kb. That is what makes cross-branch context and overlap detection possible in
the first place. On a fresh checkout of your repo, `rcorn kb sync` bootstraps
`kb/` from scratch. There is no submodule pointer to check out and nothing to
forget to init.

The clone design is also what enables multi-repo support. Several repos can
attach the same kb repo, and each gets its own top-level scope directory
named after its repo slug (`kb/reinicorn/`, `kb/my-service/`). All doc types
live inside that scope, so projects sharing one kb never collide, while
agents working in any repo can see the others' context. `rcorn init` is
additive (safe to run against a kb that already holds other repos' scopes),
and `rcorn kb list` / `rcorn kb remove-scope <name>` manage the scopes.

Nobody manages the kb checkout by hand:

- `rcorn kb sync` clones `kb/` if it's missing, pulls the latest kb state, and
  reports overlap.
- `rcorn kb publish` rebases and pushes your changes. Namespaced files (your
  branch's plan) auto-resolve in your favor; shared-file conflicts are skipped
  with a warning so you stay unblocked.
- `kb/` is gitignored, so there's no pointer commit to keep honest. A local
  pre-commit hook blocks staging it by accident, and CI fails the build if
  `kb/` is ever tracked, which is the layer a contributor can't route around.

Two escape hatches for when the workflow is in your way:

- `rcorn mode incognito`: read-only. Keep syncing and seeing others' work,
  but never publish your own.
- `rcorn mode disable`: turn hooks and background operations off entirely
  until you re-enable.

## Contributing

Reinicorn is shaped by real usage, and so far most of that usage is mine. The
most valuable thing you can contribute is a report of what helped and what got
in your way on a real team. File it with `rcorn feedback "..."` or open an
issue directly. Code and docs contributions are welcome too: see
[CONTRIBUTING.md](CONTRIBUTING.md).

## References

- [OpenAI: Harness Engineering](https://openai.com/index/harness-engineering/): the article that inspired the project.
- [core-beliefs.md](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/core-beliefs.md): the operating principles, adapted from the article for this project.
- [axi principles](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/agent-native-output-surface-axi-principles.md): the agent-experience rules the CLI's output follows.
- [Registry-driven doc types](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/registry-driven-doc-types.md): the doc-type registry that generates the CLI, linter, and wiring.
- [Skill-base agnostic Reinicorn](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/skill-base-agnostic-reinicorn-adapter-infrastructure-for-ext.md): why methodology comes from adapters instead of forked skills.
- [Remove the kb submodule](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/remove-the-kb-submodule.md): why the kb is a plain clone instead of a git submodule.
- [obra/superpowers](https://github.com/obra/superpowers) and [mattpocock/skills](https://github.com/mattpocock/skills): the upstreams for the bundled adapters.

## License

MIT.
