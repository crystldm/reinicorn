# Getting Started with reinicorn

## Prerequisites

- **Git 2.34+** — [git-scm.com/downloads](https://git-scm.com/downloads)
- **Python 3.12+** — [python.org/downloads](https://www.python.org/downloads/)
- **uv** — [docs.astral.sh/uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **gh CLI** (optional, for `--create-remote`) — [cli.github.com](https://cli.github.com/)

## Install

Reinicorn is not yet published to PyPI. Install it directly from git:

```bash
uv tool install git+https://github.com/crystldm/reinicorn.git
```

Verify: `rcorn --version`

## Set up your repo

```bash
cd your-project
rcorn init
```

The interactive prompt asks where to store the shared kb. Three options:

1. **Existing remote** — paste a Git URL your team already shares.
2. **Create on GitHub** (`--create-remote`) — creates a private repo via `gh`.
3. **Local bare repo** (`--local`) — useful for solo experiments.

`init` installs git hooks, adds the kb submodule, and creates your repo scope.

## Populate AGENTS.md

On first session start the **SessionStart hook** will nudge you if `AGENTS.md` is
incomplete. Run the Claude Code skill to fill it interactively:

```
/populate-agents-md
```

This walks through project conventions, stack, and review preferences.

## Daily workflow

```bash
rcorn kb sync       # pull latest kb — run at start of day
# ... do your work ...
rcorn kb publish    # push kb changes when done
```

Starting a new feature branch? Create an execution plan:

```bash
rcorn plan create   # scaffolds a plan doc scoped to the current branch
rcorn plan status   # check progress
rcorn plan complete # archive when the branch merges
```

## Key commands

| Command | What it does |
|---|---|
| `rcorn init` | Bootstrap reinicorn in a repo |
| `rcorn kb sync` | Pull latest kb state |
| `rcorn kb publish` | Rebase + push kb changes |
| `rcorn kb status` | Show kb health |
| `rcorn plan create` | Create execution plan for current branch |
| `reinicorn <type> create <title>` | Create a kb doc (spec, prd, retro, etc.) |
| `rcorn idea create <text>` | Quick-capture an idea |
| `rcorn kb lint` | Run kb lint rules |
| `rcorn update` | Sync local assets with installed version |
| `rcorn feedback <text>` | Report a bug or idea |
| `rcorn hooks install` | Re-install git hooks |
| `rcorn mode enable` / `rcorn mode disable` | Toggle hooks and publishing |

## Moving a local kb to GitHub

If you started with `--local` and want to share:

```bash
gh repo create my-project-kb --private --source=path/to/my-project-kb.git --push
cd kb && git remote set-url origin git@github.com:you/my-project-kb.git && cd ..
```

## Troubleshooting

**Hooks not firing** — Run `rcorn hooks install` to re-link. Check that
`.git/hooks/post-checkout` exists and is executable.

**Detached HEAD in kb** — `cd kb && git checkout main && cd ..` then
`rcorn kb sync`.

**Submodule not initialized** — `git submodule update --init --recursive`. If you
still see errors, delete `kb/` and re-run `rcorn init`.

**"not our ref" on clone** — The kb pointer is stale. Run `rcorn kb publish`
from a working checkout to update it.