# Getting started with reinicorn

## Prerequisites

- Git 2.34+: [git-scm.com/downloads](https://git-scm.com/downloads)
- Python 3.12+: [python.org/downloads](https://www.python.org/downloads/)
- uv: [docs.astral.sh/uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- gh CLI, optional: [cli.github.com](https://cli.github.com/). Used by `--create-remote` and the doc-review lane.

## Install

reinicorn is not yet published to PyPI. Install it straight from git:

```bash
uv tool install git+https://github.com/crystldm/reinicorn.git
```

Verify with `rcorn --version`.

## Set up your repo

```bash
cd your-project
rcorn init
```

The interactive prompt asks where the shared kb should live. Three options:

1. An existing remote: paste a git URL your team already shares.
2. A new private GitHub repo (`--create-remote`): created for you via `gh`.
3. A local bare repo (`--local`): useful for solo experiments.

`init` adds the kb submodule, installs the git and editor hooks, creates your
repo scope, and lays down the skills and agent instructions.

## Populate AGENTS.md

`AGENTS.md` is the entry point every agent reads first, and it starts out as a
template. On your first session the SessionStart hook nudges you if it is
incomplete. Fill it in through guided dialogue with the populate-agents-md
skill:

```
/populate-agents-md
```

It walks through project conventions, stack, and review preferences.

## Daily workflow

```bash
rcorn kb sync       # start of day: pull the latest shared kb state
# ... do your work ...
rcorn kb publish    # push your kb changes back
```

When you start a feature branch, create an execution plan:

```bash
rcorn plan create   # scaffolds a plan doc scoped to the current branch
rcorn plan status   # check progress
rcorn plan complete # archive when the branch merges
```

Design docs work the same way: `rcorn spec create "<title>"` writes a draft
from the template, and the draft goes through PR-style review before it counts
as approved. The workflow section of the [README](README.md) covers the full
loop, including doc review.

## Key commands

| Command | What it does |
|---|---|
| `rcorn init` | Bootstrap reinicorn in a repo |
| `rcorn kb sync` | Pull latest kb state |
| `rcorn kb publish` | Rebase + push kb changes |
| `rcorn kb status` | Show kb health |
| `rcorn plan create` | Create execution plan for current branch |
| `rcorn <type> create "<title>"` | Create a kb doc (spec, prd, retro, etc.) |
| `rcorn idea create "<text>"` | Capture an idea |
| `rcorn kb lint` | Run kb lint rules |
| `rcorn update` | Sync local assets with installed version |
| `rcorn feedback "<text>"` | Report a bug or idea |
| `rcorn hooks install` | Re-install git hooks |
| `rcorn mode enable` / `rcorn mode disable` | Toggle hooks and publishing |

## Moving a local kb to GitHub

If you started with `--local` and want to share:

```bash
gh repo create my-project-kb --private --source=path/to/my-project-kb.git --push
rcorn kb git remote set-url origin git@github.com:you/my-project-kb.git
```

## Troubleshooting

**Hooks not firing:** run `rcorn hooks install` to re-link, and check that
`.git/hooks/post-checkout` exists and is executable.

**Detached HEAD in kb:** run `rcorn kb git checkout main`, then
`rcorn kb sync`.

**Submodule not initialized:** run `git submodule update --init --recursive`.
If you still see errors, delete `kb/` and re-run `rcorn init`.

**"not our ref" on clone:** the kb pointer is stale. Run `rcorn kb publish`
from a working checkout to update it.

If you hit something these steps don't cover, run `rcorn feedback` and
describe it. Feedback is how the rough edges get found.
