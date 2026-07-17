#!/bin/bash
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
cd "$PROJECT_DIR"

# --- Always pull kb to avoid divergence ---
if [ -f .gitmodules ] && grep -q kb .gitmodules 2>/dev/null; then
  if [ -d kb/.git ] || [ -f kb/.git ]; then
    git -C kb fetch origin 2>/dev/null || true
    git -C kb rebase origin/main >/dev/null 2>&1 || true
  fi
fi

# --- Ambient context: compact kb dashboard (axi principle 7) ---
# Stdout from SessionStart is injected into agent context — keep it minimal.
if command -v uv &>/dev/null; then
  uv run rcorn kb status --compact 2>/dev/null || true
fi

# --- Remote-only setup below ---
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# --- Git credential rewrite for private submodules ---
# .gitmodules uses git@github.com: which needs SSH keys. In web sessions we
# only have GH_TOKEN, so rewrite to HTTPS. The token is NOT embedded in git
# config or any remote URL: a credential helper supplies it at fetch time by
# reading it from the environment, so it is never written to disk.
if [ -n "${GH_TOKEN:-}" ]; then
  git config --global url."https://github.com/".insteadOf "git@github.com:"
  # shellcheck disable=SC2016  # $GH_TOKEN must expand when git runs the helper, not now
  git config --global credential."https://github.com".helper \
    '!f() { test "$1" = get && printf "username=x-access-token\npassword=%s\n" "$GH_TOKEN"; }; f'
fi

# --- Kb submodule ---
if [ ! -f kb/.gitignore ]; then
  git submodule update --init --recursive
fi

# --- Python dev dependencies ---
uv sync --group dev --quiet

# --- Git + editor hooks ---
uv run rcorn hooks install
