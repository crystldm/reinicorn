# CI Recovery Protocol

## Purpose

Generic decision tree for agents to follow when CI fails. This is the entry point for all CI failure recovery.

---

## Prerequisites

Before starting recovery, confirm:

- [ ] You have the branch name and commit SHA of the failed run.
- [ ] You know which CI platform is in use (check `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, etc.).
- [ ] You have read the relevant platform doc in `platforms/` for this CI system.

---

## Step 1: Identify Which Job Failed

1. Read the platform doc in `platforms/` for the CI system in use.
2. Use the platform-specific commands to fetch the workflow run status.
3. Identify the specific job(s) that failed. Record:
   - Job name
   - Job step that failed
   - Exit code (if available)
4. Fetch the full log output for the failed job using platform-specific commands.

**Output of this step:** Job name, failed step name, exit code, full log text.

---

## Step 2: Classify the Failure

Read the log output and classify the failure into one of these categories:

| Category | Signals | Handler |
|----------|---------|---------|
| **Lint failure** | Linter name in output, "lint" in job name, style/format errors, import violations | `handlers/lint-failure.md` |
| **Test failure** | Test runner output, assertion errors, "test" in job name, coverage threshold failures | `handlers/test-failure.md` |
| **Build failure** | Compiler errors, type errors, missing dependencies, "build" in job name | `handlers/build-failure.md` |
| **Deploy failure** | Deployment tool output, permission errors, environment config issues, "deploy" in job name | `handlers/deploy-failure.md` |
| **Infrastructure / flaky** | Timeout with no code error, network errors, rate limits, "could not resolve host", runner out of disk, intermittent failures on unchanged code | See Step 2a below |

### Step 2a: Infrastructure / Flaky Failures

If the failure appears to be infrastructure or flaky (no code change caused it):

1. Re-trigger the failed job using the platform-specific rerun command.
2. If the job passes on retry, log the flaky failure:
   - Add an entry to `kb/tech-debt/cleanup-queue.md` with category `ci/flaky`, the job name, date, and log excerpt.
3. If the job fails again with the same error, reclassify. It may be a real failure masked by infrastructure-like symptoms.
4. If the job fails again with a different error, start over from Step 1 with the new log.

---

## Step 3: Read the Handler

1. Open the handler file matching the failure category from Step 2.
2. Follow the handler's **Diagnosis Steps** section to pinpoint the root cause.
3. Match the root cause against the handler's **Common Causes** list.
4. Read the corresponding **Fix Pattern** for that cause.

**Do not skip the diagnosis steps.** Jumping directly to a fix pattern without diagnosis leads to incorrect fixes.

---

## Step 4: Attempt the Fix

1. Implement the fix described by the handler's fix pattern.
2. Validate locally if possible:
   - For lint failures: run the linter locally.
   - For test failures: run the failing test(s) locally.
   - For build failures: run the build locally.
   - For deploy failures: local validation may not be possible -- proceed to push.
3. Commit the fix with a clear message:
   - Format: `fix(ci): <description of what was wrong and what was fixed>`
   - Reference the failed job name in the commit body.
4. Push the commit.
5. Re-trigger the CI run if it does not auto-trigger on push (use platform-specific rerun command).

---

## Step 5: Verify

1. Wait for the CI run to complete.
2. Check the result using platform-specific status commands.
3. If CI passes: recovery is complete. No further action needed.
4. If CI fails again:
   - If the same job fails with the same error: the fix did not work. Proceed to Step 6.
   - If the same job fails with a different error: start over from Step 1 with the new failure.
   - If a different job fails: start over from Step 1 for the new job.

---

## Step 6: Escalate

If the fix attempt in Step 4 did not resolve the failure, escalate to a human.

### What to Report

Provide all of the following:

1. **Failed job:** Name, step, exit code.
2. **Classification:** Which category (lint/test/build/deploy/infra) and why.
3. **Diagnosis:** What root cause was identified in Step 3.
4. **Fix attempted:** What change was made and why it was expected to work.
5. **Result after fix:** The new error output (full log excerpt).
6. **Hypothesis:** Why the fix may have failed, or what the agent could not determine.

### Escalation Format

```
CI RECOVERY ESCALATION
======================
Branch: {branch}
Commit: {sha}
CI Platform: {platform}
Failed Job: {job_name}
Failed Step: {step_name}
Exit Code: {exit_code}

Classification: {lint|test|build|deploy|infra}

Diagnosis:
{What was identified as the root cause}

Fix Attempted:
{What change was made, with file paths and line numbers}

Result After Fix:
{New error output, truncated to relevant lines}

Hypothesis:
{Why the fix did not work, or what remains unknown}

Relevant Files:
- {file1}
- {file2}
```

---

## Decision Flow Summary

```
CI fails
  |
  v
Fetch logs (platform doc)
  |
  v
Classify failure
  |
  +---> Infrastructure/flaky ---> Retry ---> Pass? Done. Fail? Reclassify.
  |
  +---> Lint / Test / Build / Deploy
          |
          v
        Read handler
          |
          v
        Diagnose root cause
          |
          v
        Apply fix pattern
          |
          v
        Push + re-trigger
          |
          v
        Pass? Done. Fail? Same error? Escalate. Different error? Restart.
```
