# Handler: Lint Failure

## Symptoms

- CI job with "lint" in its name fails.
- Log output contains linter names (ESLint, Ruff, Clippy, golangci-lint, Prettier, etc.).
- Error messages reference style rules, formatting violations, or import restrictions.
- Exit code is typically 1 (lint errors found) or 2 (lint configuration error).

---

## Common Causes (Ranked by Likelihood)

1. **Code style violation** -- New or modified code does not match the project's formatting/style rules.
2. **Import/dependency violation** -- Code imports from a forbidden module or layer (see `kb/architecture/dependency-rules.md`).
3. **Unused variable/import** -- Dead code left after refactoring.
4. **New lint rule added** -- A recently added rule catches pre-existing violations in touched files.
5. **Lint configuration error** -- Malformed lint config file, missing plugin, or incompatible plugin version.
6. **Auto-fix conflict** -- Multiple formatters/linters produce conflicting outputs (e.g., Prettier vs. ESLint).

---

## Diagnosis Steps

### Step 1: Extract the Lint Errors

1. In the CI log, find the linter's output section.
2. For each error, record:
   - File path
   - Line number
   - Rule name/ID
   - Error message
3. Count the total number of errors. If there are more than 20 errors in files you did not modify, this is likely cause #4 (new rule added). Confirm by checking recent changes to lint config files.

### Step 2: Determine if Errors Are in Your Changes

1. Run `git diff main...HEAD --name-only` (or the appropriate base branch) to get the list of files changed in this branch.
2. Compare against the files with lint errors.
3. If lint errors are ONLY in files you changed: proceed to fix patterns.
4. If lint errors are in files you did NOT change: this is likely cause #4 or #5. Check lint config history.

### Step 3: Check for Configuration Issues

If errors reference unknown rules, missing plugins, or parse errors in config files:

1. Read the lint configuration file (`.eslintrc.*`, `pyproject.toml`, `clippy.toml`, `.golangci.yml`, etc.).
2. Check if dependencies listed in the config are installed (check `package.json`, `requirements.txt`, `Cargo.toml`, etc.).
3. If a plugin is missing, this is cause #5.

---

## Fix Patterns

### Fix 1: Code Style Violation

**When:** Errors are formatting/style issues in files you modified.

1. Run the linter locally with auto-fix enabled:
   - ESLint: `npx eslint --fix <files>`
   - Prettier: `npx prettier --write <files>`
   - Ruff: `ruff check --fix <files> && ruff format <files>`
   - Clippy: `cargo clippy --fix --allow-dirty`
   - gofmt: `gofmt -w <files>`
2. Review the changes. Verify auto-fix did not alter logic.
3. If auto-fix does not resolve all errors, manually fix the remaining ones by reading the rule documentation.

### Fix 2: Import/Dependency Violation

**When:** Errors reference forbidden imports or layer violations.

1. Read `kb/architecture/dependency-rules.md` to understand the allowed dependency directions.
2. Identify what the forbidden import provides (a type, a function, a constant).
3. Determine the correct way to access that functionality:
   - If it is a type: extract the type to a shared types module that both layers can import.
   - If it is a function: check if the function belongs in a utility module or if the dependency direction should be inverted (caller provides it via dependency injection).
4. Refactor the import to comply with dependency rules.

### Fix 3: Unused Variable/Import

**When:** Errors flag unused identifiers.

1. Verify the identifier is truly unused (not referenced dynamically or in a way the linter cannot detect).
2. If genuinely unused: remove it.
3. If it is needed but the linter cannot detect usage: add a linter suppression comment with a justification.
   - ESLint: `// eslint-disable-next-line no-unused-vars -- used by <reason>`
   - Clippy: `#[allow(dead_code)] // used by <reason>`
   - Ruff: `# noqa: F841 -- used by <reason>`

### Fix 4: New Rule Catching Pre-existing Violations

**When:** Errors are in files you did not modify, or the error count is disproportionate to your changes.

1. Confirm by checking lint config change history: `git log --oneline -5 -- <lint-config-files>`.
2. If a new rule was added by someone else, you have two options:
   - **Option A:** Fix the pre-existing violations if they are small in number (< 10 files).
   - **Option B:** If violations are widespread (> 10 files), escalate. Do not fix hundreds of files in a CI recovery commit.
3. If you added the new rule yourself, fix all violations it catches.

### Fix 5: Lint Configuration Error

**When:** Errors reference unknown rules, missing plugins, or config parse failures.

1. If a plugin is missing: add it to the project's dependency file and install.
2. If a rule name is wrong: check the plugin documentation for the correct rule name.
3. If the config file has a syntax error: fix the syntax. Use the linter's config validation command if available:
   - ESLint: `npx eslint --print-config <file>`
   - Ruff: `ruff check --show-settings`

### Fix 6: Auto-fix Conflict

**When:** Running one formatter undoes the changes of another, or the CI runs two formatters that disagree.

1. Identify which two tools conflict (check CI job steps for the order they run).
2. Configure them to be compatible:
   - For ESLint + Prettier: install `eslint-config-prettier` to disable ESLint rules that conflict with Prettier.
   - For other combinations: check the tools' documentation for interoperability settings.
3. If tools cannot be reconciled, escalate to the developer for a decision on which tool takes precedence.

---

## When to Escalate

Escalate to a human (via the escalation format in `recovery-protocol.md`) when:

- Lint errors are in more than 10 files you did not modify and no recent config change explains it.
- The lint configuration is complex and the error is in the configuration itself, not in code.
- Two formatters/linters conflict and there is no obvious resolution.
- A lint suppression is needed but the reason is unclear -- do not suppress without justification.
- The lint rule appears to be wrong (flags correct code). Report the false positive rather than suppressing it.
