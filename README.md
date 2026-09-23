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

Everything here comes back to the harness engineering article's central claim:
the repository is the source of truth. If context lives in a chat thread or in
someone's head, agents can't see it. The kb is where that context gets written
down so the whole team can see it, agents on other branches included. The
workflow exists to get the important stuff written down, and then to make sure
you can trust it once it is.

The second idea from the article is mechanical enforcement over documented
conventions. A rule that only exists in prose will get broken eventually, so
wherever possible the rules are code. That's what most of what follows is for.
The full set of beliefs behind the design is in
[core-beliefs.md](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/core-beliefs.md).

Every document in the kb is a markdown file with a frontmatter block, filed
under `kb/<scope>/` (one scope per repo). You create documents through the
CLI, not by hand. The registry decides which documents exist, where they go,
and what rules apply to them. It ships with a spec-driven set of types, but
you can change them or replace them entirely, and everything below works the
same for your types as for the shipped ones.

### Document types

A document type is a name plus whatever rules you attach to it. Each rule is
something you turn on for the type, and each one has a consequence the whole
team will see:

- Give it a home and a naming pattern, and `rcorn <type> create` files each
  document there with the frontmatter filled in. Documents can be named by
  slug (`specs/<slug>.md`), scoped to a branch
  (`exec-plans/active/<branch>/plan.md`), or numbered (`RFC-0007-<slug>.md`).
- Mark it protected, and the editor hooks reject direct writes to its
  directory. A document can't exist without the provenance fields the CLI
  stamps on it.
- Give it required sections, and the template scaffolds each one with a hint.
  `rcorn kb lint` flags any document still missing one.
- Mark it review-gated, and a new document starts as a draft that has to pass
  through a PR before it's actionable. Until then, `list` and `show` skip it
  unless you ask, and nothing else in the kb can build on it.
- Give it an index file, and the linter tells you when the index goes stale.
- Make it appendable, and `create` adds an entry to one running file instead
  of writing a new document. The repo's golden principles work this way.

### Relations between types

Two rules connect one type to another, and that's where the workflow actually
comes from:

- Say a type depends on another, and each of its documents has to name an
  approved document of that type. A plan names the spec it implements, so a
  plan built on a draft spec shows up as a lint finding, and a branch whose
  plan names a draft can't be pushed.
- Say a type closes another, and the closing document lives next to the one
  it closes. Mark the relation required, and the closing document has to be
  written before the other one is finalized. A retro closes an execution plan,
  for example, so `rcorn plan complete` refuses until the retro is filled in;
  `--abandon` is the recorded way to drop a plan without one. Leave it
  optional and `complete` just warns. Either way, the closed document's
  directory moves from `active` to `completed` with both files in it.

### Where the rules are enforced

The rules run at five points:

- While you write: `rcorn kb lint` reports every document that's missing a
  section, builds on a draft, or is still an empty scaffold, plus every plan
  still active after its branch merged.
- When you push: the pre-push hook stops a branch whose documents depend on
  something that isn't approved yet.
- When the PR is reviewed: the "Process gate" check runs the lints for just
  that branch's documents, so a PR can't merge with an empty or missing
  retro. It also prints the registry in effect, so if someone weakened a
  rule, the reviewer sees it right there.
- When the branch is done: `rcorn <type> complete` won't archive without the
  document that closes it.
- After merge: the post-merge hook archives the plans of branches that are
  gone from origin, through the same `complete`.

### Changing the registry

The registry lives in `kb/<scope>/doc-types.yaml`, next to the documents it
governs, and goes out with `rcorn kb publish` like any other kb file.
`rcorn doc-types show` lists every type in effect, each marked `built-in` or
`overlay`. To customize, copy a row, change one line, and publish. You can
change a shipped type (only the lines you list change), add a type of your own
(all it needs is a home, a naming pattern, and an addressing mode), or turn a
shipped type off with `disabled: true`. If the file has a mistake, the CLI
stops and names the offending key instead of quietly falling back to the
shipped set, and `rcorn doc-types show --schema` gives your editor a schema to
validate against. [Customizing the process](#customizing-the-process) has
worked examples; the full contract is in
[the process-as-config spec](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/process-as-config-doc-type-registry-overlay-and-declarative.md).

## The shipped defaults

Out of the box, the registry has seven types. Two relations tie them into a
workflow: a plan depends on an approved spec, and a retro closes a plan. In
`doc-types.yaml` terms, that's:

```yaml
doc_types:
  plan:
    depends_on: {field: spec, type: spec, status: approved}
  retro:
    closes: {type: plan, required: true}
```

| Type | Create | What it is | Rules |
|------|--------|------------|-------|
| spec | `rcorn spec create "<title>"` | The implementation contract: problem, design goals, design, non-goals | review-gated, indexed |
| prd | `rcorn prd create "<title>"` | Product requirements: overview, user stories, acceptance criteria, out of scope, open questions | indexed |
| debt | `rcorn debt create "<title>"` | Tech-debt entry: impact and remediation plan | indexed |
| idea | `rcorn idea create "<idea>"` | Quick capture, filed by author | none |
| plan | `rcorn plan create` | Per-branch execution plan: goal, acceptance criteria, tasks | depends on an approved spec; closed by a retro |
| retro | `rcorn retro create` | Per-branch retrospective: what went well, what to improve, lessons, actions, spec drift | closes the plan, required |
| principle | `rcorn principle add "<title>"` | One entry in the repo's golden principles | appendable |

All but `principle` are protected, and every type with sections gets them
scaffolded and linted.

### The default workflow

Work starts with a spec, the implementation contract. Specs come from wherever
work comes from: a PRD, a roadmap conversation, a bug that exposed a design
flaw, an idea someone captured weeks ago. If you have the superpowers adapter
installed (see [The skill set](#the-skill-set)), its brainstorming skill turns
that raw intent into a design through dialogue. Either way,
`rcorn spec create` turns the design into a draft in the kb. Specs are
review-gated, so a draft only counts once it passes doc review (next section).
The code is reviewed as normal, of course, but having the team collaborate on
and validate the intent first saves a lot of time and effort.

With a spec in hand, work moves to a feature branch. `rcorn plan create`
scaffolds an execution plan scoped to that branch and publishes it to the kb.
Plans depend on an approved spec, so the pre-push hook refuses a branch whose
plan names a draft. Every branch's plan sits in the same place, so
`rcorn kb status` can compare active branches and flag overlap before two
people quietly rewrite the same file (the article calls this cross-branch
awareness). With the superpowers adapter, the executing-plans skill works
through the plan step by step.

When the branch merges, `rcorn plan complete` archives the plan. The retro
closes the plan and is required, so `complete` refuses until the retro is
filled in; `--abandon` is the escape hatch, and it gets recorded. The retro's
Spec Drift section lists every deviation from the plan's spec along with what
was done about it (amended, debted, or accepted), or just says "None." That
way drift gets disclosed where the reviewer is already reading.

A few commands sit outside the main loop. `rcorn idea create` is for the
thought that hits while you're in the middle of something else: file it and
get back to work, instead of losing it or chasing it. `rcorn debt create`
catalogs tech debt as you run into it. Debt compounds fast when agents are
writing the code, since a shortcut taken today becomes a pattern agents copy
tomorrow. `rcorn principle add` appends to the repo's golden principles, so a
team preference gets written down once and enforced from then on, instead of
argued again in every review.

With the defaults, `rcorn kb lint` checks cross-links, doc freshness, required
sections, plans built on unapproved specs, retros left as empty scaffolds, and
plans still active after their branch merged. The "Process gate" CI job runs
the per-branch subset on every PR.

### Doc review

Review-gated types (only `spec` by default) get the same review treatment as
code, since specs shape everything built after them. The process is kept
lightweight, though: a correction is cheap, and waiting on a review is
expensive. `rcorn spec create` writes the draft to `specs/drafts/` on kb main,
where everyone can see it right away, but `rcorn spec list` and `show` leave
it out unless you ask for drafts. When it's ready:

```bash
rcorn review start <slug>     # push a review branch, open a PR, request reviewers
rcorn review push <slug>      # sync later edits into the PR
rcorn review merge <slug>     # merge the approved PR, land the doc, delete the draft
rcorn review status           # open reviews in this repo scope
```

The kb checkout never leaves `main`. The review branch only exists on the
remote, so reviewers get a full-file GitHub diff with inline comments and your
working copy stays where it is. Merging (from the CLI or the GitHub UI) flips
the draft to `approved` and lands it at `specs/<slug>.md`.

`rcorn review setup` installs two small CI workflows in the kb repo. One lets
a merge from the browser finish the cleanup by itself. The other puts two real
status checks on every kb PR: Doc lint (`rcorn kb lint` against the PR) and
Candidate integrity (the PR adds exactly its one doc, and it still matches the
draft on main). The `reinicorn-doc-review` ruleset requires both before
anything merges into kb main; direct `rcorn kb publish` pushes aren't
affected. Rerun `rcorn review setup --force` after upgrading to pick up new
workflow versions. You don't need `gh` for any of this. Without it, reinicorn
pushes the branch and hands you the PR link to open yourself.

### Customizing the process

Say you want the retro optional again, without the Spec Drift section. That's
two lines in `kb/<scope>/doc-types.yaml`:

```yaml
doc_types:
  retro:
    closes: {type: plan, required: false}
    required_sections: [What Went Well, What Could Be Improved, Lessons Learned, Action Items]
```

Or say you want a different process altogether, RFC → ADR. That takes a few
more:

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

That gets you `rcorn rfc create` going through the review lane with
`RFC-0001-…` numbering, `rcorn adr create`, the draft-refs lint and pre-push
gate on `adr.rfc`, required-section lint on both, and no retro or completion
step at all, since nothing closes anything.

## The CLI

`rcorn` is the one entry point for kb operations. It hides the git plumbing so
neither you nor your agents touch the kb clone directly. Run bare `rcorn` for
a live status view (branch, active docs, overlap), and `rcorn help` for the
full manual.

The [axi spec](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/agent-native-output-surface-axi-principles.md)
sets the output rules: content first, structured errors on stdout where agents
will actually see them, and a `next:` footer suggesting the likely next
command. Tests enforce these, so read the spec before you change how any
command talks.

Every type in the registry gets its own commands. With the shipped set,
`<type>` is one of `spec`, `prd`, `debt`, `idea`, `plan`, `retro`, or
`principle`:

| Command | Purpose |
|---|---|
| `rcorn <type> create "<title>"` | Create a document from its template. Branch-scoped types take no title; an appendable type uses `add` (`rcorn principle add "<title>"`). `rcorn help` lists the exact form per type |
| `rcorn <type> show [<slug>\|<branch>] [--full]` | Read a document (truncated preview by default). Slug-named types take a slug, branch-scoped types default to the current branch; an appendable type has no `show` |
| `rcorn <type> list [--include-drafts]` | List the documents of a slug-named type (branch-scoped and appendable types have no `list`) |
| `rcorn <type> status` | Where the current branch's document stands (types that something closes, so `plan` by default) |
| `rcorn <type> complete [branch] [--abandon]` | Archive the branch's document; refuses until the document that closes it is filled in, `--abandon` drops it instead |
| `rcorn doc-types show [--schema]` | Print the effective registry, or the JSON Schema for the config file |

The rest work the same no matter what's in your registry:

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
ships two native skills of its own, and past those it has no opinion on how
you develop:

- `using-reinicorn`: how to find and use skills; loads first, every session
- `populate-agents-md`: fill in `AGENTS.md` through guided dialogue

Methodology (brainstorming, planning, TDD, code review, worktrees, and so on)
comes from a skill-set adapter you install:

```bash
rcorn skills install superpowers
```

This fetches a pinned, kb-compatible build of
[obra/superpowers](https://github.com/obra/superpowers) (brainstorming,
writing-plans, executing-plans, test-driven-development, systematic-debugging,
and the rest of that pack), patched so it writes docs through `rcorn` instead
of following its own conventions. `rcorn skills list` shows the bundled
adapters, and `rcorn skills status` shows what's installed. If your team has
its own skill set, point `rcorn skills install` at your own adapter definition
to wire it up.

Whatever skill set you have installed (or none), `using-reinicorn`'s generated
wiring doc
([`.agents/skills/using-reinicorn/references/skillset-wiring.md`](.agents/skills/using-reinicorn/references/skillset-wiring.md))
maps every doc type to its creation command and the skill(s) to run first.
With no adapter installed, the creation commands alone are the contract.

## KB as a shared clone

The kb is an ordinary git clone at `kb/`, gitignored in every repo that uses
it, tracking a shared repo on `main` only (linear history, no branches). Every
branch and every contributor reads and writes the same kb, which is what makes
cross-branch context and overlap detection work. On a fresh checkout of your
repo, `rcorn kb sync` bootstraps `kb/` from scratch. There's no pointer to
check out, so there's nothing to forget to init.

The same design is what makes multi-repo support work. Several repos can
attach the same kb repo, and each gets its own top-level scope directory named
after its repo slug (`kb/reinicorn/`, `kb/my-service/`). All of a repo's doc
types live inside its scope, so projects sharing a kb never collide, and
agents working in one repo can still see the others' context. `rcorn init` is
additive, so it's safe to run against a kb that already holds other repos'
scopes. `rcorn kb list` and `rcorn kb remove-scope <name>` manage the scopes.

Nobody manages the kb checkout by hand:

- `rcorn kb sync` clones `kb/` if it's missing, pulls the latest kb state, and
  reports overlap.
- `rcorn kb publish` rebases and pushes your changes. Namespaced files (your
  branch's plan) auto-resolve in your favor, and conflicts on shared files get
  skipped with a warning so you're not blocked.
- `kb/` is gitignored, so there's no pointer commit to keep honest. A local
  pre-commit hook stops you from staging it by accident, and CI is the real
  backstop: it fails the build if `kb/` is ever tracked, which a contributor
  can't route around.

And two escape hatches for when the workflow gets in your way:

- `rcorn mode incognito`: read-only. You keep syncing and seeing everyone
  else's work, but never publish your own.
- `rcorn mode disable`: turns hooks and background operations off entirely
  until you re-enable them.

## Contributing

Reinicorn is shaped by real usage, so the most valuable contribution is
feedback on what helps and what gets in the way. File it with
`rcorn feedback "..."` or open an issue directly. Code and docs contributions
are welcome too: see [CONTRIBUTING.md](CONTRIBUTING.md).

## References

- [OpenAI: Harness Engineering](https://openai.com/index/harness-engineering/): the article that inspired the project.
- [obra/superpowers](https://github.com/obra/superpowers): the upstream for the bundled `superpowers` skill-set adapter.
- [core-beliefs.md](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/core-beliefs.md): the operating principles, adapted from the article for this project.
- [axi principles](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/agent-native-output-surface-axi-principles.md): the agent-experience rules the CLI's output follows.
- [Remove the kb submodule](https://github.com/crystldm/reinicorn-kb/blob/main/reinicorn/specs/remove-the-kb-submodule.md): why the kb is a plain clone instead of a git submodule.

## License

MIT.
