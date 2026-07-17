# Platform: [PLATFORM NAME]

## Overview

<!-- Brief description of this CI platform and any prerequisites (CLI tools, authentication). -->

---

## Fetching Workflow Run Status

<!-- REQUIRED: Provide commands to: -->
<!-- 1. List recent runs for a specific branch -->
<!-- 2. View a specific run's details -->
<!-- 3. Identify which jobs within a run failed -->

### List Recent Runs

```bash
# Command to list recent CI runs for a branch
```

### View a Specific Run

```bash
# Command to view details of a specific run by ID
```

### View Failed Jobs

```bash
# Command to filter/display only the failed jobs in a run
```

---

## Fetching Logs

<!-- REQUIRED: Provide commands to: -->
<!-- 1. Fetch logs for failed jobs/steps only -->
<!-- 2. Fetch full logs for an entire run -->
<!-- 3. Any alternative methods for log retrieval (API, web download, etc.) -->

### Fetch Failed Job Logs

```bash
# Command to get logs for failed steps only
```

### Fetch Full Run Logs

```bash
# Command to get complete logs for all jobs in a run
```

---

## Re-triggering Jobs

<!-- REQUIRED: Provide commands to: -->
<!-- 1. Rerun only failed jobs -->
<!-- 2. Rerun the entire pipeline/workflow -->
<!-- 3. Rerun a specific job (if supported) -->
<!-- 4. Wait for/watch a run until completion (if supported) -->

### Rerun Failed Jobs

```bash
# Command to rerun only the jobs that failed
```

### Rerun Entire Pipeline

```bash
# Command to rerun all jobs in the pipeline
```

### Rerun a Specific Job

```bash
# Command to rerun a single specific job (or note if not supported)
```

### Wait for Completion

```bash
# Command to block until the run completes and report status (or polling alternative)
```

---

## Reading Artifacts

<!-- REQUIRED: Provide commands to: -->
<!-- 1. List artifacts produced by a run -->
<!-- 2. Download a specific artifact -->
<!-- 3. Download all artifacts -->

### List Artifacts

```bash
# Command to list artifacts for a run
```

### Download Artifacts

```bash
# Command to download a specific artifact by name or ID
# Command to download all artifacts
```

---

## Checking Pipeline/Workflow Syntax

<!-- REQUIRED: Provide instructions to: -->
<!-- 1. Locate the pipeline configuration files -->
<!-- 2. Validate syntax locally (tool or command) -->
<!-- 3. List common syntax pitfalls for this platform -->

### Configuration File Location

<!-- Where does this platform store its pipeline configuration? (e.g., .gitlab-ci.yml, Jenkinsfile, etc.) -->

### Local Validation

```bash
# Command or tool to validate pipeline syntax without running it
```

### Common Syntax Issues

<!-- List 3-5 common syntax mistakes for this platform -->

1. <!-- Issue 1 -->
2. <!-- Issue 2 -->
3. <!-- Issue 3 -->

---

## Useful API Endpoints / Commands

<!-- OPTIONAL but recommended: Additional commands or API endpoints useful for diagnosis. -->
<!-- Examples: getting annotations, check statuses, commit statuses, etc. -->

---

## Common Diagnosis Sequence

<!-- REQUIRED: A copy-paste-ready sequence of commands that an agent would run -->
<!-- to go from "CI failed" to "I have the logs and can diagnose." -->

```bash
# Step 1: Find the failed run
# Step 2: Identify which jobs failed
# Step 3: Fetch the failed logs
# Step 4: (After fix) Rerun failed jobs
# Step 5: Watch for result
```

---

## Authentication Notes

<!-- REQUIRED: How to verify authentication. What to do if not authenticated. -->
<!-- What permissions are required for log access and re-triggering. -->

---

## Contributing Checklist

Before submitting this platform integration, verify:

- [ ] All REQUIRED sections are filled in with working commands.
- [ ] Commands have been tested against a real CI run on this platform.
- [ ] Authentication requirements are documented.
- [ ] The common diagnosis sequence works end-to-end.
- [ ] Error messages from the platform are described (what they look like, what they mean).
- [ ] Any platform-specific quirks or limitations are noted.
