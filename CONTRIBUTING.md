# Contributing to Reinicorn

Thanks for your interest. A few things to know up front.

## Project status

Reinicorn is early and not yet accepting general outside contributions. Issues
and discussion are welcome; unsolicited pull requests may sit unreviewed for a
while. If you want to work on something substantial, open an issue first so we
can talk about it before you spend time on it.

## Human contributions only

Reinicorn is a harness for real human teams. Contributions must come from a
person with genuine intent behind them.

**We do not accept pure AI-bot contributions**: issues, pull requests, or
comments generated and submitted by an automated agent with no human directing
the work and standing behind the result. Using AI tools to help you write code
is fine (this project is built with them). Pointing a bot at the repo to
open PRs on its own is not. Such contributions will be closed without review.

## Development setup

Reinicorn uses [`uv`](https://docs.astral.sh/uv/) for environment and package
management.

```bash
uv sync                 # install deps into .venv
uv run pytest           # run the test suite (reports coverage)
uv run ruff check .     # lint
uv run pyright          # type-check (src/ only)
```

### Coverage

`uv run pytest` measures branch coverage of `src/reinicorn` and prints a
per-file table with the uncovered lines. The run fails below **85%** total.
That floor is a ratchet: raise it as coverage improves, don't lower it to
turn a red build green.

CI publishes the same table to the workflow run's summary page, and attaches
a browsable line-by-line HTML report as the `coverage-html` artifact. For
that report locally:

```bash
uv run pytest --cov-report=html
# then open htmlcov/index.html in your browser
```

Knowledge-base operations go through the CLI, never raw git in `kb/`:

```bash
rcorn kb status
rcorn kb sync
```

## Pull requests

- Branch off `main`; keep PRs focused.
- Follow [Conventional Commits](https://www.conventionalcommits.org/) for commit
  and PR titles (`feat:`, `fix:`, `test:`, `chore:`, …).
- Make sure `pytest`, `ruff`, and `pyright` are green before requesting review.
- PRs are squash-merged, so the PR title becomes the commit message.

By contributing you agree your contributions are licensed under the MIT License
(see [LICENSE](LICENSE)).
