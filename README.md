# Reinicorn

Reinicorn is a tool and skill set for managing agentic coding workflows in
close collaboration with human developers. Inspired by OpenAI's
[Harness Engineering](https://openai.com/index/harness-engineering/) article,
Reinicorn puts the principles outlined there into practice in a simple,
straightforward way: a set of skills, hooks (both `git` and harness), and the
`rcorn` CLI, built on [AXI](https://github.com/kunchenguid/axi) principles. No
MCP, no vector database, no extra cloud storage (excuse the LLM-ism). It keeps
your docs organized and helps minimize the slop.

Reinicorn is for creating, maintaining, and curating a knowledgebase
repository, using whatever workflow documents you want. Document types and
their relations to each other are defined in a registry. For a typical
spec-driven-development workflow (such as the one Reinicorn ships with), you
could have a spec -> spec-review -> plan -> execute -> retro workflow. Mark a
document as review-gated, it must pass through PR before becoming actionable.
Mark a document as closing another, then it must be created before its closee
is finalized; a retro closing an execution plan for example. The methodology
and skills that drive the workflow are pluggable: install the bundled adapter
for [obra/superpowers](https://github.com/obra/superpowers) or bring your own
(see [The skill set](#the-skill-set)). Every document comes from a template, so
provenance and review status are first-class rather than something you remember
to add.

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
├── workflows/              # kb-repo CI workflows installed by `rcorn review setup`
├── upgrades/               # Version-to-version upgrade notes
├── kb/                     # The shared knowledgebase (gitignored clone)
└── tests/                  # Test suite
```

## How it works

Everything here follows from the harness engineering article's central claim:
the repository is the source of truth. If context lives in a chat thread or in
someone's head, agents can't see it. The kb is where it becomes visible to the
whole team, including agents working on other branches. The workflow exists to
get the important context written down, and to make sure it can be trusted
once it is. The full set of beliefs behind the design is in
[core-beliefs.md](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/core-beliefs.md).

Every governed doc is a markdown file with a frontmatter block, living under
`kb/<scope>/` (one scope per repo) and created through the CLI, never by
hand. What a `<type>` *is* comes from a registry row. The engine never asks
what a doc is, only what it can do, so the rest of this section names no
type: `<type>` is any row, `<closer>` and `<closee>` are two rows joined by a
relation.

### A doc type is a bundle of behaviors

| Behavior | Row fields | What the engine does with it |
|---|---|---|
| Addressed by slug, by branch, or a singleton | `addressing`, `filename` | Shapes the CLI argument and the path. `{slug}` names a doc; `{branch}` scopes it to a git branch; a singleton is one file. A `{seq:04}` placeholder numbers a corpus (`RFC-0007`) and stamps the number into the doc's `id` |
| Protected | `protected` | Direct writes to the directory are rejected by the editor hook; docs exist only through the CLI, with their provenance fields |
| Structured | `required_sections`, `section_hints` | The template scaffolds the headers, with an italic placeholder hint where the row gives one; the `kb/required-sections` lint checks them while the doc is being authored |
| Review-gated | `gated` | `create` writes to `drafts/`, invisible to `list` and `show` unless asked; approval goes through the review lane (`rcorn review …`) |
| Indexed | `index_file` | The `kb/docs-freshness` lint and the dashboard track the index |
| Appendable | `create_mode: append` | `create` appends an entry to the one file instead of writing a new one |
| Seeded | `readme_label` | A row in the kb README that `rcorn init` seeds |
| Frontmatter vocabulary | `fields`, `required_fields` | Which extra keys a doc may or must carry. `branch` (branch-addressed) and `id` (`{seq}`) are added by the engine |

### Two relations join types

- `depends_on: {field, type, status}` on a `<dependent>` row: each doc's
  `field:` must resolve to a tracked doc of `type` with `status`, or be
  `N/A`. A placeholder counts as undeclared.
- `closes: {type, required}` on a `<closer>` row: the closer closes
  `<closee>` and lives inside its directory. A closee's filename is
  `{stage}/{branch}/<name>`, stage being `active` or `completed`; the closer's
  is a bare name. `rcorn <closee> complete` moves the directory with both
  docs from active to completed. When `required`, it refuses until the closer
  is filled; `--abandon` drops the closee instead. One closer per closee, and
  a closer is not itself closable.

### Enforcement is a fixed set of events

The events never change; what varies is the registry they read.

| Event | Reads | Rule |
|---|---|---|
| `rcorn kb lint` | `required_sections` | `kb/required-sections`: every doc of every structured type carries its headers |
| `rcorn kb lint` | `depends_on` | `kb/draft-refs`: a dependent doc points at a draft or in-review target |
| `rcorn kb lint` | `closes` | `kb/closer-filled`: an active closee's required closer exists but is still the placeholder scaffold |
| `rcorn kb lint` | `closes` | `kb/lifecycle`: an active closee whose branch is merged or deleted |
| pre-push hook | `depends_on` | Refuses to push a branch whose dependent doc points at an unapproved or undeclared target. Network failures fail open, loudly |
| pre-merge CI (`rcorn _process-gate <branch>`) | `required_sections`, `depends_on`, `closes` | The branch-scoped subset of the lints, with a *missing* required closer counting; every finding blocks. Prints the effective registry so a weakened process is visible in the check log |
| `rcorn <closee> complete` | `closes` | Refuses without a filled required closer |
| post-merge hook | `closes` | Archives active closees whose branch is gone from origin, through the same `complete` |

There is no rule language. A behavior is an engine field; a gate the engine
lacks is an engine change with its own spec. The config composes behaviors, it
cannot define them.

### The CLI is generated from the registry

Every row gets a creation command, `rcorn <type> <create_verb>`, where the
verb is the row's `create_verb` (`create` unless the row says otherwise;
the appendable `principle` row uses `add`) and the argument shape follows
`title_source`: a title, free text, or nothing. Every row gets
`rcorn <type> show`; slug-addressed rows also get `list`. Every closee gets
`status` and `complete [--abandon]`. `rcorn doc-types show` prints the
effective registry with each row marked `built-in` or `overlay`;
`--schema` emits a JSON Schema for the config file.

### The config file

`kb/<scope>/doc-types.yaml`, next to the docs it governs, published with
`rcorn kb publish` like any kb file. Three operations:

- **Override** a built-in row by listing only the fields that change
  (`required_sections:` replaces the list wholesale; there is no merging).
- **Add** a row. `dir_path`, `filename` and `addressing` are mandatory; the
  rest take defaults.
- **Remove** a built-in row with `disabled: true`. A disabled row takes its
  own relations with it.

A broken file fails closed with the path and offending key; it never silently
reverts to defaults. Copy a row from `rcorn doc-types show`, change one line,
publish: that is the customization loop. The full contract is in
[the process-as-config spec](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/process-as-config-doc-type-registry-overlay-and-declarative.md).

## The shipped defaults

With no config file, the registry holds seven rows that encode a spec-driven
workflow. Expressed as config, the two relations that drive it are:

```yaml
doc_types:
  plan:
    depends_on: {field: spec, type: spec, status: approved}
  retro:
    closes: {type: plan, required: true}
```

| Type | Create | Addressing | Behaviors | Required sections |
|------|--------|------------|-----------|-------------------|
| spec | `rcorn spec create "<title>"` | slug | protected, gated, indexed, seeded | Problem, Design Goals, Design, Non-Goals |
| prd | `rcorn prd create "<title>"` | slug | protected, indexed, seeded | Overview, User Stories, Acceptance Criteria, Out of Scope, Open Questions |
| debt | `rcorn debt create "<title>"` | slug | protected, indexed, seeded | Impact, Remediation Plan |
| idea | `rcorn idea create "<idea>"` | slug, filed by author | protected | none |
| plan | `rcorn plan create` | branch | protected, seeded, depends on an approved spec, closed by retro | Goal, Acceptance Criteria, Tasks |
| retro | `rcorn retro create` | branch | protected, closes plan (required) | What Went Well, What Could Be Improved, Lessons Learned, Action Items, Spec Drift |
| principle | `rcorn principle add "<title>"` | singleton | appendable, seeded | none |

### The default workflow

Work starts with a **spec**, the implementation contract. Specs come from
wherever work comes from: a PRD, a roadmap conversation, a bug that exposed a
design flaw, an idea captured weeks earlier. With the superpowers adapter
installed (see [The skill set](#the-skill-set)), the brainstorming skill turns
that raw intent into a design through dialogue; `rcorn spec create` turns the
design into a draft in the kb either way. Because `spec` is gated, a draft
only becomes authoritative after doc review (next section).

With a spec in hand, work moves to a feature branch. `rcorn plan create`
scaffolds an execution plan scoped to that branch and publishes it to the kb.
Because `plan` depends on an approved spec, the pre-push hook refuses a
branch whose plan names a draft. Because every branch's plan is visible in one
place, `rcorn kb status` can compare active branches and flag overlap before
two people silently rewrite the same file, what the article calls cross-branch
awareness. With the superpowers adapter installed, the executing-plans skill
works the plan step by step. When the branch merges, `rcorn plan complete`
archives it, and because `retro` closes `plan` as a required closer, it
refuses without a filled retro; `--abandon` is the recorded escape hatch. The
retro's Spec Drift section states every deviation from the plan's declared
spec with a disposition (amended, debted or accepted), or the single word
"None." — so drift is disclosed where the reviewer reads it.

Two capture commands sit outside the main loop. `rcorn idea create` is for
the thought that strikes while you're doing something else: file it and stay
on task, instead of losing it or chasing it. `rcorn debt create` catalogs tech
debt as you encounter it. Debt compounds fast in agent-assisted codebases,
since a shortcut taken today becomes a pattern agents replicate tomorrow.
Team taste gets the same treatment: `rcorn principle add` appends to the
repo's golden principles, capturing a human preference once so it can be
enforced continuously instead of re-litigated in every review.

The other belief doing heavy lifting here is mechanical enforcement over
documented conventions: a rule that exists only in prose will eventually be
violated, so wherever possible the rules are code. That is what the events
above are. With the defaults, `rcorn kb lint` checks cross-links, doc
freshness, required sections, plans built on unapproved specs, retros left as
empty scaffolds, and plans still active after their branch merged; the
"Process gate" CI job runs the per-branch subset against every PR.

### Doc review

A gated type (only `spec` by default) gets the same review treatment as code,
because specs shape everything built after them. The process stays
lightweight, though: corrections are cheap and waiting is expensive.
`rcorn spec create` writes the draft to `specs/drafts/` on kb main, visible to
everyone immediately but excluded from `rcorn spec list` and `show` unless
you ask for drafts. When it's ready:

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
setup` installs two small CI workflows in the kb repo: one so a browser merge
finishes the cleanup on its own, and one that puts two real status checks on
every kb PR — **Doc lint** (`rcorn kb lint` against the PR) and **Candidate
integrity** (the PR adds exactly its one doc, still in sync with the draft on
main). The `reinicorn-doc-review` ruleset requires both before a merge into
kb main; direct `rcorn kb publish` pushes are unaffected. Rerun `rcorn review
setup --force` after upgrading to pick up new workflow versions. `gh` is
optional at every step; without it, reinicorn pushes the branch and hands you
the PR link to open yourself.

### Customizing the process

Making the retro optional again and dropping its Spec Drift section is two
lines in `kb/<scope>/doc-types.yaml`:

```yaml
doc_types:
  retro:
    closes: {type: plan, required: false}
    required_sections: [What Went Well, What Could Be Improved, Lessons Learned, Action Items]
```

A different process altogether, RFC → ADR, is a handful more:

```yaml
doc_types:
  spec:  {disabled: true}
  plan:  {disabled: true}
  retro: {disabled: true}
  rfc:
    dir_path: rfcs
    filename: "RFC-{seq:04}-{slug}.md"
    addressing: slug
    gated: true
    required_sections: [Summary, Motivation, Detailed Design, Drawbacks, Alternatives]
    fields: [superseded_by]
  adr:
    dir_path: decisions
    filename: "{slug}.md"
    addressing: slug
    required_sections: [Context, Decision, Consequences]
    fields: [rfc]
    depends_on: {field: rfc, type: rfc, status: approved}
```

That gives `rcorn rfc create` through the review lane with `RFC-0001-…`
numbering, `rcorn adr create`, the draft-refs lint and pre-push gate on
`adr.rfc`, required-section lint on both, and no retro or completion
machinery at all. Zero engine changes.

## The CLI

`rcorn` is the single entry point for kb operations; it hides the git plumbing
so neither humans nor agents touch the kb clone directly. Bare `rcorn` shows
a live status home view (branch, active docs, overlap), and `rcorn help` has
the full manual.

The [axi spec](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/agent-native-output-surface-axi-principles.md)
sets the output rules: content first, structured errors on stdout where agents
can see them, and a `next:` footer suggesting the likely next command. Tests
enforce these rules, so read the spec before changing how any command talks.

Generated per registry row (with the defaults, `<type>` is one of `spec`,
`prd`, `debt`, `idea`, `plan`, `retro`, `principle`):

| Command | Purpose |
|---|---|
| `rcorn <type> <create_verb> [...]` | Create a doc from its template; the verb (`create`, or `add` for the appendable `principle`) and argument shape come from the row (`rcorn help`, or the wiring doc) |
| `rcorn <type> show [<slug>\|<branch>] [--full]` | Read a kb doc (truncated preview by default) |
| `rcorn <type> list [--include-drafts]` | List docs of a slug-addressed type |
| `rcorn <closee> status` | Lifecycle status for the current branch (`plan` by default) |
| `rcorn <closee> complete [branch] [--abandon]` | Archive to the completed stage; refuses without a filled required closer, `--abandon` drops it |
| `rcorn doc-types show [--schema]` | Print the effective registry, or the JSON Schema for the config file |

Fixed:

| Command | Purpose |
|---|---|
| `rcorn kb sync` | Pull latest kb state |
| `rcorn kb publish` | Push kb changes (rebase + push) |
| `rcorn kb status` | Kb health, active docs, overlap, stale docs |
| `rcorn kb status --compact` | ≤10-line dashboard for agent context (session-start hook) |
| `rcorn kb lint` | Run kb lint rules |
| `rcorn kb list` | List repo scopes in the kb |
| `rcorn kb remove-scope <name>` | Remove a repo scope |
| `rcorn kb git <args...>` | Raw git passthrough inside the kb |
| `rcorn review start\|push\|merge\|cancel\|link\|status` | The doc-review lane for gated types (see above) |
| `rcorn review setup [--force]` | Install kb-repo CI workflows (cleanup + status checks) and the ruleset |
| `rcorn skills install <name>` | Install a skill-set adapter |
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
