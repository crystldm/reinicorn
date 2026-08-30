#!/usr/bin/env bash
# lint-markdown — Lint rule: docs/markdown
#
# Runs rumdl over the project's markdown. File selection and exclusions come
# from .rumdl.toml — this rule builds no file list of its own. The kb clone
# at kb/ is gitignored in the host repo (invisible to a gitignore-respecting
# pass), so it gets a second pass of its own.
#
# Exit 0 if clean or rumdl is unavailable. Exit 1 if any violation.

set -uo pipefail

PROJECT_ROOT="${1:-$(cd "$(dirname "$0")/../../.." && pwd)}"
RUMDL_CONFIG="$PROJECT_ROOT/.rumdl.toml"

# Resolve the runner: installed rumdl, else the project env via uv.
# --project keeps uv resolving the same env when cwd is the kb pass.
if command -v rumdl &>/dev/null; then
  RUNNER=(rumdl)
elif uv run --no-sync --project "$PROJECT_ROOT" rumdl --version &>/dev/null; then
  RUNNER=(uv run --no-sync --project "$PROJECT_ROOT" rumdl)
else
  echo "rumdl not found — skipping. Install with: pip install rumdl"
  exit 0
fi

cd "$PROJECT_ROOT" || exit 1

FAILED=0

# lint_tree <target> — run rumdl against <target> (a path relative to
# PROJECT_ROOT — "." for the repo itself, "kb" for the kb clone), reformat
# concise output (path:line:col: [MDxxx] message) to framework format
# (path:line — [MDxxx] message).
#
# -c is passed explicitly (rather than relying on rumdl's own config
# discovery) because it does double duty: (1) rumdl's discovery does not
# walk up past a nested .git boundary, so without it the kb/ clone (its own
# git repo) would silently lint against rumdl's defaults instead of the
# house style; (2) passing an explicit config path also makes rumdl report
# every path relative to the config file's directory (PROJECT_ROOT) rather
# than relative to cwd, so "kb" already comes back "kb/..."-prefixed with
# no manual prefixing needed here. --respect-gitignore (on by default) does
# not apply to explicitly-listed paths, so passing "kb" directly still
# reaches it despite it being gitignored.
lint_tree() {
  local target="$1" out rc line matched=0
  out=$("${RUNNER[@]}" check --output-format concise -c "$RUMDL_CONFIG" "$target" 2>&1)
  rc=$?
  while IFS= read -r line; do
    if [[ "$line" =~ ^([^:]+):([0-9]+):[0-9]+:\ (\[MD[0-9]+\]\ .+)$ ]]; then
      echo "${BASH_REMATCH[1]}:${BASH_REMATCH[2]} — ${BASH_REMATCH[3]}"
      matched=1
      FAILED=1
    fi
  done <<<"$out"
  # A non-zero exit with no parseable violations is a tool failure (bad
  # config, crash) — surface it instead of silently passing.
  if [ "$rc" -ne 0 ] && [ "$matched" -eq 0 ]; then
    echo "${target}: rumdl failed (exit $rc)"
    FAILED=1
  fi
}

lint_tree "."
if [ -e "kb/.git" ]; then
  lint_tree "kb"
fi

exit "$FAILED"
