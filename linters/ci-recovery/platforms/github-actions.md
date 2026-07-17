# Platform: GitHub Actions

## Overview

Instructions for agents to interact with GitHub Actions CI. All commands use the `gh` CLI, which must be authenticated and available in the agent's environment.

---

## Fetching Workflow Run Status

### List Recent Runs for the Current Branch

```bash
gh run list --branch <branch-name> --limit 5
```

Output includes: run ID, status, conclusion, workflow name, branch, commit SHA.

### View a Specific Run

```bash
gh run view <run-id>
```

Output includes: run status, jobs, and their individual statuses.

### View a Specific Run with Failed Jobs Only

```bash
gh run view <run-id> --json jobs --jq '.jobs[] | select(.conclusion == "failure") | {name: .name, conclusion: .conclusion, steps: [.steps[] | select(.conclusion == "failure")]}'
```

---

## Fetching Logs

### Download Full Logs for a Run

```bash
gh run view <run-id> --log-failed
```

This outputs only the logs for failed steps, which is usually sufficient for diagnosis.

### Download All Logs (When Failed Logs Are Not Enough)

```bash
gh run view <run-id> --log
```

Warning: This can produce very large output. Prefer `--log-failed` first.

### Fetch Logs via API (For More Control)

```bash
# Get the log download URL
gh api repos/{owner}/{repo}/actions/runs/{run-id}/logs -i

# Download logs as a zip
gh api repos/{owner}/{repo}/actions/runs/{run-id}/logs > logs.zip
unzip logs.zip -d ci-logs/
```

Each job's logs will be in a separate file within the zip.

---

## Re-triggering Jobs

### Rerun All Failed Jobs

```bash
gh run rerun <run-id> --failed
```

This reruns only the jobs that failed, not the entire workflow.

### Rerun the Entire Workflow

```bash
gh run rerun <run-id>
```

### Rerun a Specific Job

```bash
# First, get the job ID
gh run view <run-id> --json jobs --jq '.jobs[] | {id: .databaseId, name: .name}'

# Then rerun that specific job
gh api -X POST repos/{owner}/{repo}/actions/jobs/{job-id}/rerun
```

### Wait for a Run to Complete

```bash
gh run watch <run-id>
```

This blocks until the run completes and reports the final status.

---

## Reading Artifacts

### List Artifacts for a Run

```bash
gh run view <run-id> --json artifacts --jq '.artifacts[] | {name: .name, size: .sizeInBytes}'
```

### Download Artifacts

```bash
# Download a specific artifact by name
gh run download <run-id> --name <artifact-name>

# Download all artifacts
gh run download <run-id>
```

Artifacts are downloaded to the current directory. Common artifacts include test reports, coverage reports, and build outputs.

---

## Checking Workflow File Syntax

### Validate Workflow Files Locally

GitHub Actions workflow files are in `.github/workflows/`. Validate YAML syntax:

```bash
# Check YAML syntax (requires yq or a YAML linter)
yq eval '.on' .github/workflows/<workflow-file>.yml
```

### Common Workflow Syntax Issues

1. **Indentation errors:** YAML is indentation-sensitive. Verify consistent use of spaces (not tabs).
2. **Expression syntax:** GitHub Actions expressions use `${{ }}`. Missing braces cause silent failures.
3. **Invalid action references:** Check that action versions exist: `uses: actions/checkout@v4` -- verify the tag exists.
4. **Missing required inputs:** Some actions require inputs. Check the action's README for required fields.

### Validate by Triggering a Dry Run

GitHub Actions does not have a native dry-run mode. To validate syntax without running:

1. Check the workflow file parses as valid YAML.
2. Verify all `uses:` references point to existing actions and valid versions.
3. Verify all `${{ }}` expressions reference valid context objects (`github.*`, `secrets.*`, `env.*`, `steps.*`, etc.).
4. Push to a branch and check if the workflow appears in the Actions tab (GitHub validates syntax on push).

---

## Useful API Endpoints

### Get Workflow Run Details

```bash
gh api repos/{owner}/{repo}/actions/runs/{run-id}
```

### Get Check Suite Results

```bash
gh api repos/{owner}/{repo}/commits/{sha}/check-runs --jq '.check_runs[] | {name: .name, conclusion: .conclusion, output: .output.summary}'
```

### Get Annotations (Inline Errors)

```bash
gh api repos/{owner}/{repo}/check-runs/{check-run-id}/annotations
```

Annotations contain file-level error details that some CI tools (linters, compilers) produce.

---

## Common GitHub Actions Patterns

### Finding the Run for the Current Branch

```bash
# Get the most recent failed run on the current branch
BRANCH=$(git branch --show-current)
gh run list --branch "$BRANCH" --status failure --limit 1 --json databaseId --jq '.[0].databaseId'
```

### Full Diagnosis Sequence

```bash
# 1. Find the failed run
RUN_ID=$(gh run list --branch "$BRANCH" --status failure --limit 1 --json databaseId --jq '.[0].databaseId')

# 2. See which jobs failed
gh run view "$RUN_ID" --json jobs --jq '.jobs[] | select(.conclusion == "failure") | .name'

# 3. Get the failed logs
gh run view "$RUN_ID" --log-failed

# 4. After fix, rerun failed jobs
gh run rerun "$RUN_ID" --failed

# 5. Watch for result
gh run watch "$RUN_ID"
```

---

## Authentication Notes

- `gh` must be authenticated. Run `gh auth status` to verify.
- If `gh` is not authenticated, the agent cannot fetch logs or re-trigger jobs. Escalate to the developer to authenticate.
- Repository access is determined by the authenticated user's permissions. If commands return 403/404, the user may lack write access to the repo.
