# Reinicorn

Reinicorn is a doc-governance layer for agentic coding. It gives a team one
shared knowledgebase for the `.md` files agents and humans generate — specs,
plans, PRDs, retros, tech debt, ideas, golden principles — and the discipline
around them: every doc is created from a registered template through the
`rcorn` CLI, protected paths reject hand-written files, a linter checks what
the templates can't, and specs go through a lightweight review lane before
anything is built on them.

Inspired by OpenAI's
[Harness Engineering](https://openai.com/index/harness-engineering/) article,
Reinicorn puts its central claim into practice: the repository is the source of
truth, and if context lives in a chat thread or in someone's head, agents can't
see it. The tool is a set of git and harness hooks, a small skill layer, and a
CLI built on [AXI](https://github.com/kunchenguid/axi) principles. No MCP, no
vector database, no extra cloud storage (excuse the LLM-ism).

Reinicorn takes no position on development methodology. How you brainstorm,
plan, debug, or review comes from whatever skill set you install — the bundled
adapter for [obra/superpowers](https://github.com/obra/superpowers), or your
own. Reinicorn owns three things and leaves the rest alone:

1. **Where docs live** — the kb, a shared git clone with one scope per repo.
2. **How docs are created** — through `rcorn`, from a registered template,
   never by hand.
3. **Which skills gate which docs** — a wiring doc generated from the doc-type
   registry and the installed skill set.

The kb is a separate repository, always on `main` except for single-doc review
PRs. One kb can be shared across multiple repositories, so all domain knowledge
sits in one place, accessible to every agent across a multi-repo, multi-team
project.

The core loop works: capture → review → implement → retro. Plenty is still
missing, and many ideas are open for implementation in the
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
CLI), or a local bare repo for solo experiments (`--local`). It then clones the
kb, installs the git and editor hooks, and lays down the native skills and
agent instructions for your platforms. Optionally, add a methodology skill set
(see [The skill layer](#the-skill-layer)):

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
├── adapters/               # Bundled skill-set adapter definitions (superpowers)
├── .agents/skills/         # Native skills (.claude/skills symlinks here); adapter skills install here, gitignored
├── hooks/                  # Git hooks: pre-commit, post-checkout, post-merge, pre-push
├── editor-hooks/           # Editor guard hooks: doc-template + raw-kb-git guards
├── linters/                # Stack-agnostic kb lint framework and rules
├── platform-instructions/  # Per-platform pointer files (claude, cursor, copilot)
├── templates/              # AGENTS.md template laid down by init
├── workflows/              # CI workflow installed by `rcorn review setup`
├── upgrades/               # Version-to-version upgrade notes
├── kb/                     # The shared knowledgebase (gitignored clone)
└── tests/                  # Test suite
```

## Doc governance

Agent-assisted work produces documents faster than anyone can curate them.
Left alone they end up scattered across `docs/`, chat logs, and PR
descriptions, with no way to tell a draft from a decision or a stale plan from
a live one. Reinicorn's answer is the belief the harness engineering article
calls mechanical enforcement over documented conventions: a rule that exists
only in prose will eventually be violated, so wherever possible the rules are
code. The full set of beliefs behind the design is in
[core-beliefs.md](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/core-beliefs.md).

### Doc types come from a registry

Every kind of document Reinicorn manages is a row in one registry, and that
row is the single source of truth for the type: its directory in the kb, its
filename pattern, its template body and required sections, whether it is
protected, whether it is review-gated, and how it is addressed (by slug, by
branch, or as a singleton). The CLI's `rcorn <type> create|show|list` groups,
the linter's section checks, the editor guards, and the skill wiring doc are
all generated from those rows. Adding or renaming a doc type is a registry
change, not a sweep through the codebase.

The shipped types, each with its template and protected location:

| Type | Create command | What it is |
|------|----------------|------------|
| spec | `rcorn spec create "<title>"` | The implementation contract: problem, design goals, design, non-goals. Review-gated. |
| prd | `rcorn prd create "<title>"` | Product requirements: overview, user stories, acceptance criteria, out of scope |
| plan | `rcorn plan create` | Per-branch execution plan: goal, acceptance criteria, tasks |
| retro | `rcorn retro create` | Per-branch retrospective: what went well, what to improve, lessons, actions |
| debt | `rcorn debt create "<title>"` | Tech-debt entry: impact and remediation plan |
| idea | `rcorn idea create "<text>"` | Quick capture, filed by author |
| principle | `rcorn principle add "<title>"` | Appends a golden principle to the repo's ruleset |

### Every doc is created through the CLI

A doc can't exist in the kb without its provenance. `rcorn <type> create`
lays down the frontmatter (type, slug, lifecycle, status, author, origin,
`human_validated`) and the required sections from the registry template; the
protected kb paths (`specs/`, `prds/`, `tech-debt/`, `exec-plans/`, `ideas/`)
reject direct writes through editor hooks on Claude Code, Cursor, and
Copilot, and `rcorn kb git` is the only sanctioned way to touch the clone's
git state. The hooks apply regardless of which skill set is installed, so a
methodology that likes to write `docs/plans/whatever.md` still ends up going
through `rcorn plan create`.

Plans are the one type bound to a branch rather than a slug. `rcorn plan
create` scaffolds the plan for the current branch and publishes it to the kb;
because every branch's plan is visible in one place, `rcorn kb status` can
compare active branches and flag overlap before two people silently rewrite
the same file — what the article calls cross-branch awareness. When the branch
merges, `rcorn plan complete` archives the plan and asks for a retro, because
lessons that never get written down are lost.

Two capture types sit outside any workflow. `rcorn idea create` is for the
thought that strikes while you're doing something else: file it and stay on
task. `rcorn debt create` catalogs tech debt as you encounter it, since a
shortcut taken today becomes a pattern agents replicate tomorrow.

### The linter checks what templates can't

`rcorn kb lint` runs the rules in `linters/`: frontmatter is valid, cross-links resolve, index
files are fresh, plans have their required structure, and no plan builds on
a spec that is still a draft. Team taste gets the same treatment: `rcorn
principle add` appends to the repo's golden principles, capturing a human
preference once so it can be enforced continuously instead of re-litigated in
every review. Principles are meant to be mechanical — if you can't imagine a
lint rule for it, it's a convention, not a principle.

### Specs go through review

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
branch and hands you the PR link to open yourself.

Review gating is a registry flag, so which types are gated is a project
decision rather than a hardcoded one. Specs ship gated; ideas and debt don't.

## The skill layer

Skills live in `.agents/skills/` (the Agent Skills open standard, configurable)
and load natively on Claude Code, Cursor, GitHub Copilot, and Codex. Reinicorn
ships two **native** skills, managed by `rcorn update`:

- `using-reinicorn`: the doc-lifecycle contract — where docs live, the
  creation rule, and the wiring doc. Loads first, every session.
- `populate-agents-md`: fill in `AGENTS.md` through guided dialogue.

That's the whole native opinion. Methodology — brainstorming, planning, TDD,
debugging, code review, worktrees — comes from a **skill-set adapter**:

```bash
rcorn skills install superpowers
```

An adapter is a declarative definition (`adapters/<name>/adapter.yaml`): an
upstream repo pinned to a commit, an explicit list of skills to take, a series
of real git patches plus append blocks that make those skills kb-compatible
(write docs through `rcorn`, respect protected paths), and a **wiring** map
from doc types to the skills that should run before creating them. Same
adapter plus same pin gives byte-identical output, and a patch that no longer
applies fails the install loudly rather than landing half-way. The repo
contains no forked third-party skill text — only adapter definitions — and
adapter-installed skills are gitignored in your project, with a lockfile at
`.reinicorn/skillset-lock.json` tracking the pin and per-file hashes.

The bundled `superpowers` adapter installs a pinned build of
[obra/superpowers](https://github.com/obra/superpowers). `rcorn skills list`
shows bundled adapters, `rcorn skills status` reports what's installed and
whether you've edited it locally, and `rcorn skills update` re-applies or
re-pins. `rcorn skills install ./path/to/adapter` wires up a house skill set
the same way.

Whichever skill set (if any) is installed, the generated wiring doc at
`.agents/skills/using-reinicorn/references/skillset-wiring.md` maps every
registered doc type to its creation command and the skill(s) to invoke first.
With no adapter installed, the creation commands alone are the contract — the
kb, the templates, the hooks, and the linter all work standalone.

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
| `rcorn skills install <name\|path>` | Install a skill-set adapter (bundled name or local directory) |
| `rcorn skills status` / `list` | Installed adapter state / bundled adapters |
| `rcorn skills update [--ref X] [--force]` | Re-apply or re-pin the installed adapter |
| `rcorn mode enable\|disable\|incognito\|status` | Mode toggles |
| `rcorn init [...]` | Set up reinicorn in this repo |
| `rcorn hooks install` | Install git and editor hooks |
| `rcorn update [--diff X]` | Re-sync bundled files (native skills, hooks, linters) to the installed version |
| `rcorn feedback [text]` | Open a GitHub issue on the reinicorn repo itself |

## KB as a shared clone

The kb is an ordinary git clone at `kb/`, gitignored in every repo that
attaches it, tracking a shared repo on `main` only (linear history, no
branches). Every branch and contributor reads and writes the same kb, which
is what makes cross-branch context and overlap detection possible. On a
fresh checkout of your repo, `rcorn kb sync` bootstraps `kb/` from scratch —
there's no pointer to check out, so nothing to forget to init.

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
- [core-beliefs.md](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/core-beliefs.md): the operating principles, adapted from the article for this project.
- [axi principles](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/agent-native-output-surface-axi-principles.md): the agent-experience rules the CLI's output follows.
- [Skill-base agnostic Reinicorn](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/skill-base-agnostic-reinicorn-adapter-infrastructure-for-ext.md): why methodology comes from adapters instead of forked skills.
- [Registry-driven doc types](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/registry-driven-doc-types.md): the doc-type registry that generates the CLI, linter, and wiring.
- [Remove the kb submodule](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/remove-the-kb-submodule.md): why the kb is a plain clone instead of a git submodule.
- [obra/superpowers](https://github.com/obra/superpowers): the upstream for the bundled `superpowers` skill-set adapter.

## License

MIT.
