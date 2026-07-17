# Handler: Deploy Failure

## Symptoms

- CI job with "deploy", "release", or "publish" in its name fails.
- Log output contains deployment tool output (Terraform, Kubernetes, Docker, AWS CLI, Vercel, Netlify, etc.).
- Error messages reference permissions, configuration, resource limits, health check failures, or image push errors.
- Exit code varies by tool.

---

## Common Causes (Ranked by Likelihood)

1. **Configuration error** -- Deployment config references a resource, variable, or secret that does not exist or is misconfigured.
2. **Health check failure** -- Application deploys but fails its health check, causing rollback.
3. **Permission / credential error** -- Deployment credentials are expired, missing, or lack required permissions.
4. **Resource limit** -- Cloud provider quota exceeded (instances, IPs, storage, etc.).
5. **Image build failure** -- Docker image fails to build or push (distinct from application build failure).
6. **Environment variable missing** -- Application starts but crashes because a required env var is not set in the target environment.
7. **Infrastructure drift** -- The expected infrastructure state does not match reality (e.g., Terraform state is out of sync).
8. **Rollback from previous failure** -- The deploy system is stuck in a rollback state from a previous failed deploy.

---

## Diagnosis Steps

### Step 1: Identify the Deploy Stage

Deploy failures can occur at multiple stages. Determine where in the pipeline the failure happened:

1. **Image/artifact build** -- Failure before anything is deployed.
2. **Push/upload** -- Artifact built but could not be pushed to registry/storage.
3. **Infrastructure provisioning** -- Cloud resources could not be created or updated.
4. **Application deployment** -- Artifact deployed but application did not start successfully.
5. **Post-deploy verification** -- Application started but health checks or smoke tests failed.

### Step 2: Extract the Error

1. Find the first error in the deploy log (deploy tools are often verbose; scroll past info/debug lines).
2. Record:
   - Deploy tool name and version
   - Error message
   - Resource or service that failed
   - Any referenced configuration file or variable name

### Step 3: Distinguish Code Errors from Infrastructure Errors

This is the critical classification for deploy failures:

- **Code error:** Your application code causes the deploy to fail (crash on startup, failed health check due to a bug, bad config value you committed). You can fix this.
- **Infrastructure error:** The deploy environment itself has a problem (expired creds, quota limits, network issues, drift). You usually cannot fix this from code. Escalate.

Ask: "If I reverted my last commit, would this deploy succeed?" If yes: code error. If no: infrastructure error.

---

## Fix Patterns

### Fix 1: Configuration Error

**When:** Deploy config references a nonexistent resource, variable, or has a syntax error.

1. Identify the config file from the error message (Dockerfile, docker-compose.yml, terraform/*.tf, k8s manifests, serverless.yml, vercel.json, etc.).
2. Read the file and find the referenced resource or variable.
3. Fix the reference:
   - If the resource name changed: update the reference.
   - If a variable was renamed: update the config to use the new name.
   - If there is a syntax error: fix it.
4. If the config file has a validation command, run it:
   - Terraform: `terraform validate`
   - Kubernetes: `kubectl apply --dry-run=client -f <file>`
   - Docker Compose: `docker compose config`

### Fix 2: Health Check Failure

**When:** Application deploys but the health check endpoint returns an error or times out.

1. Check the health check configuration (which endpoint, what timeout, how many retries).
2. Read the application logs from the deploy environment (if accessible via CI).
3. Common sub-causes:
   - **Application crashes on startup:** Check for missing env vars (cause #6), bad config, or a bug in initialization code.
   - **Health endpoint returns error:** The endpoint exists but returns 5xx. Check what the health check endpoint does (database connectivity, dependency checks).
   - **Health endpoint times out:** Application is too slow to start. Check if startup time increased due to your changes.
4. Fix the underlying issue (see the relevant sub-cause) rather than weakening the health check.

### Fix 3: Permission / Credential Error

**When:** Error messages contain "access denied", "unauthorized", "forbidden", "expired token", or similar.

1. Do NOT attempt to fix credentials yourself. Credentials should never be in code.
2. Escalate immediately. Report:
   - Which credential or role is failing.
   - The exact error message.
   - Whether this credential worked on a previous deploy (check recent CI history).

### Fix 4: Resource Limit

**When:** Error messages reference quotas, limits, or "capacity" issues.

1. This is an infrastructure issue. You cannot fix it from code.
2. Escalate with:
   - The specific resource type and limit cited.
   - The current usage if reported in the error.
   - Whether this is a new limit or has been hit before.

### Fix 5: Image Build Failure

**When:** Dockerfile or container build fails during the deploy pipeline.

1. Read the Docker build log to find the failing step.
2. Common sub-causes:
   - **COPY fails:** A file referenced in COPY does not exist or is in `.dockerignore`.
   - **RUN fails:** A build command inside the container fails (missing system dependency, failed download).
   - **Base image unavailable:** The base image tag no longer exists or the registry is unreachable.
3. Fix the Dockerfile or the files it references.
4. Test locally: `docker build -t test .`

### Fix 6: Missing Environment Variable

**When:** Application starts but immediately crashes with an error about a missing or undefined variable.

1. Identify the variable name from the crash log.
2. Check if the variable is defined in:
   - The deploy environment's config (CI secrets, environment config, .env files in deploy config).
   - Your code's expected environment variables list (if one exists).
3. If the variable is new (you added it):
   - Add it to the deploy environment's configuration.
   - If you cannot access the deploy config, escalate with the variable name and its required value/format.
4. If the variable is not new but missing: escalate. Someone may have removed it.

### Fix 7: Infrastructure Drift

**When:** Terraform or IaC tool reports that expected resources do not exist, have different properties, or that the state file is inconsistent.

1. Do NOT run `terraform apply` or equivalent without explicit human approval.
2. Escalate immediately with:
   - The drift description from the error.
   - Whether recent infrastructure changes were made outside the IaC tool.

### Fix 8: Stuck Rollback State

**When:** Deploy tool reports that a previous deployment is still rolling back or in a failed state.

1. Check the deploy tool's status command for the current deployment state.
2. If the tool supports it, check if the previous rollback can be manually completed or skipped.
3. Escalate. Manual intervention in deployment state is high-risk and should not be done by an agent without human approval.

---

## When to Escalate

Escalate to a human (via the escalation format in `recovery-protocol.md`) when:

- **Always escalate** for: credential errors, resource limits, infrastructure drift, stuck rollback state.
- Health check failures where the root cause is not in your code changes.
- Deploy config changes that affect production environments.
- Any situation where you are unsure whether a change affects production data or availability.
- Image build failures caused by external dependencies (base image unavailable, package registry down).
- The deploy failure is in a production or staging environment and the deploy cannot be easily rolled back.

**Deploy failures have the highest escalation rate of all failure types.** When in doubt, escalate. A bad deploy fix can cause production outages.
