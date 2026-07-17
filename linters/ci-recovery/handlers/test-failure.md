# Handler: Test Failure

## Symptoms

- CI job with "test" in its name fails.
- Log output contains test runner output (Jest, pytest, cargo test, go test, etc.).
- Error messages include assertion failures, test timeouts, or coverage threshold violations.
- Exit code is typically 1 (test failures) or a runner-specific code.

---

## Common Causes (Ranked by Likelihood)

1. **Broken assertion** -- Your code change altered behavior that a test asserts against.
2. **Missing test update** -- You changed a function signature, return value, or data structure but did not update the tests that depend on it.
3. **Flaky test** -- The test passes sometimes and fails sometimes due to timing, ordering, or external dependency.
4. **Environment mismatch** -- Test passes locally but fails in CI due to different environment (OS, Node version, env vars, database state).
5. **Coverage threshold violation** -- Tests pass but code coverage dropped below the configured threshold.
6. **Test infrastructure issue** -- Test database unavailable, fixture loading fails, test container fails to start.
7. **Snapshot mismatch** -- Snapshot tests detect intentional UI/output changes that need snapshot updates.

---

## Diagnosis Steps

### Step 1: Extract the Failing Tests

1. In the CI log, find the test runner's summary output.
2. For each failure, record:
   - Test file path
   - Test name / description
   - Expected value
   - Actual value
   - Error message / stack trace
3. Count failing tests. If many unrelated tests fail, this may be cause #4 or #6.

### Step 2: Determine Relationship to Your Changes

1. Run `git diff main...HEAD --name-only` to list changed files.
2. For each failing test:
   - Is the test file itself in your changeset? If yes: you may have broken the test (cause #2).
   - Does the test exercise code that you modified? If yes: your change may have altered behavior (cause #1).
   - Is the test completely unrelated to your changes? If yes: likely cause #3, #4, or #6.

### Step 3: Check for Flakiness

If failing tests are unrelated to your changes:

1. Check if the same test has failed in recent CI runs on other branches.
2. If available, check test history / flaky test reports.
3. If the test is known flaky: re-trigger CI once. If it passes, log the flaky test in `kb/tech-debt/cleanup-queue.md`.
4. If the test is not known to be flaky and is unrelated to your changes: check for environment issues (cause #4 or #6).

### Step 4: Check Coverage Thresholds

If the test runner reports coverage below a threshold but all tests pass:

1. Find the coverage configuration (jest.config, pytest.ini, .nycrc, etc.).
2. Identify which files or lines caused the drop.
3. Check if your new code lacks tests.

---

## Fix Patterns

### Fix 1: Broken Assertion

**When:** A test asserts an old value or behavior that your code intentionally changed.

1. Read the failing test to understand what it verifies.
2. Determine if the old behavior or the new behavior is correct:
   - If your change is intentional and the test's expected value is now wrong: update the test's expected value to match the new behavior.
   - If your change accidentally broke correct behavior: fix your code, not the test.
3. If updating the test, verify the test still covers meaningful behavior. Do not weaken assertions just to make them pass.

**Example:**
```
// Before your change, function returned { status: "pending" }
// After your change, it returns { status: "active", activatedAt: <timestamp> }
// Test expected { status: "pending" } -- update to expect { status: "active" } and add assertion for activatedAt
```

### Fix 2: Missing Test Update

**When:** You changed a function signature, type, or data shape and tests use the old interface.

1. Find all test files that import or call the changed function/type.
2. Update each call site to match the new signature.
3. Update expected values if the return type changed.
4. Run the tests locally to verify.

### Fix 3: Flaky Test

**When:** The test is unrelated to your changes and has failed intermittently before.

1. Re-trigger the CI run once.
2. If it passes, add the test to `kb/tech-debt/cleanup-queue.md`:
   ```
   - category: test/flaky
     test: <test name>
     file: <test file path>
     date: <today>
     notes: Failed on <branch> despite no related changes. Passed on retry.
   ```
3. If it fails again, it may not be flaky. Reclassify and re-diagnose.

### Fix 4: Environment Mismatch

**When:** Tests pass locally but fail in CI, with errors suggesting different runtime behavior.

1. Compare the CI environment against your local environment:
   - Language/runtime version (check CI config for version pins).
   - Operating system (CI often runs Linux; you may run macOS/Windows).
   - Environment variables (check for `.env` files not committed, or CI-specific env vars).
   - Database/service availability.
2. If the issue is a version mismatch: pin your local version to match CI, reproduce the failure, then fix.
3. If the issue is a missing env var: add it to CI configuration or make the code handle its absence.

### Fix 5: Coverage Threshold Violation

**When:** All tests pass but coverage dropped below the configured minimum.

1. Identify which lines/branches in your new code lack test coverage.
2. Write tests for the uncovered paths:
   - Prioritize branches (if/else) and error handling paths.
   - Prioritize public API methods over internal helpers.
3. Run coverage locally to confirm you meet the threshold before pushing.

### Fix 6: Test Infrastructure Issue

**When:** Tests fail with errors about connection refused, fixture not found, container not started, etc.

1. Check if the CI workflow provisions required services (databases, caches, etc.).
2. Check if service health checks pass in the CI log before tests run.
3. If a service is missing from CI config: add it (but escalate first -- CI config changes are significant).
4. If the service exists but failed to start: this is infrastructure. Re-trigger CI. If it persists, escalate.

### Fix 7: Snapshot Mismatch

**When:** Tests fail because a snapshot (UI, CLI output, serialized data) does not match the stored version.

1. Review the diff between the old snapshot and the new output.
2. If the change is intentional (you changed the UI or output format): update the snapshots.
   - Jest: `npx jest --updateSnapshot`
   - Insta (Rust): `cargo insta review`
   - Other: check the test framework's snapshot update command.
3. If the change is unintentional: your code has an unexpected side effect. Fix the code, not the snapshot.

---

## When to Escalate

Escalate to a human (via the escalation format in `recovery-protocol.md`) when:

- Multiple unrelated tests fail and the cause is not flakiness or environment.
- A test failure reveals that your code change conflicts with intended behavior and you are unsure which behavior is correct.
- The test infrastructure is broken and you cannot fix it without CI config changes you are not confident about.
- Coverage thresholds cannot be met without writing tests for code you did not write and do not fully understand.
- A flaky test has been re-triggered 2+ times and still fails intermittently. It needs human investigation.
