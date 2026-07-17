# Handler: Build Failure

## Symptoms

- CI job with "build" or "compile" in its name fails.
- Log output contains compiler errors, type errors, or linker errors.
- Error messages reference unresolved imports, missing types, or syntax errors.
- Dependency installation fails (npm install, pip install, cargo build, etc.).
- Exit code is typically 1 (compilation error) or a build-tool-specific code.

---

## Common Causes (Ranked by Likelihood)

1. **Type error or syntax error** -- New code has a compilation error that was not caught locally.
2. **Missing or incompatible dependency** -- A dependency is not in the lockfile, or version conflicts exist.
3. **Merge conflict artifact** -- Conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) left in source files after a merge.
4. **Environment difference** -- Build succeeds locally but fails in CI due to different toolchain version, OS, or cached state.
5. **Missing generated code** -- Code generation step (protobuf, GraphQL codegen, ORM schema) was not run before commit.
6. **Circular dependency** -- New import creates a circular reference the build tool cannot resolve.
7. **Out-of-memory or disk** -- Build process runs out of resources in CI (large compile targets, asset processing).

---

## Diagnosis Steps

### Step 1: Extract the Build Errors

1. In the CI log, locate the first error. Build logs often contain cascading errors -- the first error is usually the root cause.
2. Record for the first error:
   - File path
   - Line number
   - Error code (if any)
   - Error message
3. Check if subsequent errors are cascading (caused by the first error) or independent.

### Step 2: Check for Conflict Markers

1. Search the codebase for merge conflict markers:
   - Search for `<<<<<<<` in all source files.
   - Search for `=======` combined with `>>>>>>>` in the same file.
2. If found: this is cause #3. Fix by resolving the merge properly.

### Step 3: Check Dependency State

1. Compare the lockfile (`package-lock.json`, `yarn.lock`, `Cargo.lock`, `poetry.lock`, `go.sum`) against the manifest file (`package.json`, `Cargo.toml`, `pyproject.toml`, `go.mod`).
2. Check if any new imports in your code reference packages not listed in the manifest.
3. Check if the lockfile was committed. Some CI configurations require the lockfile to be present.

### Step 4: Check for Environment Differences

If the error involves a feature, flag, or API that exists locally but not in CI:

1. Compare language/toolchain version between local and CI (check CI config for version pins).
2. Check if the error references an API or feature introduced in a newer version than CI uses.
3. Check if CI uses a different target platform (e.g., building for Linux in CI but developing on macOS).

---

## Fix Patterns

### Fix 1: Type Error or Syntax Error

**When:** The compiler reports a type mismatch, unknown identifier, or syntax problem in code you wrote.

1. Read the error message carefully. The compiler usually reports:
   - What it expected.
   - What it found instead.
   - The exact file and line.
2. Open the file at the reported line. Fix the type mismatch or syntax error.
3. Check if the error cascades: after fixing the first error, mentally trace whether downstream errors will also be resolved.
4. Build locally to confirm the fix before pushing.

**Example:**
```
error[E0308]: mismatched types
  --> src/billing/invoice.rs:42:12
   |
42 |     amount: String,
   |            ^^^^^^ expected `Decimal`, found `String`
```
Fix: Change the type to `Decimal` or convert the value appropriately.

### Fix 2: Missing or Incompatible Dependency

**When:** Build fails on import resolution or dependency installation.

1. If a package is missing:
   - Add it to the manifest file with the correct version.
   - Run the package manager's install/lock command to update the lockfile.
   - Commit both the manifest and lockfile changes.
2. If versions conflict:
   - Read the error to identify which packages conflict.
   - Check which version each consumer requires.
   - Resolve by finding a compatible version or updating the conflicting consumer.
3. Build locally to confirm resolution.

### Fix 3: Merge Conflict Artifact

**When:** Conflict markers are found in source files.

1. Open each file containing conflict markers.
2. Resolve the conflict by choosing the correct code (or combining both sides as appropriate).
3. Remove all conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).
4. Build locally to confirm the resolved code compiles.

### Fix 4: Environment Difference

**When:** Build uses a language feature or API not available in the CI toolchain version.

1. Check the CI configuration for the pinned toolchain version.
2. Options (in order of preference):
   - **Option A:** Rewrite the code to use APIs available in the CI version.
   - **Option B:** Update the CI toolchain version pin (escalate first -- this affects all builds).
3. If you choose Option A, install the matching toolchain version locally to verify compatibility.

### Fix 5: Missing Generated Code

**When:** Build fails because it references types or files that should have been generated by a code generation tool.

1. Identify which code generator is needed (check `Makefile`, `build.rs`, `package.json` scripts, etc.).
2. Run the code generation step locally.
3. Check the project convention:
   - If generated code is committed: commit the generated files.
   - If generated code is not committed: ensure the CI pipeline runs the generation step before the build step. If it does not, escalate.

### Fix 6: Circular Dependency

**When:** Build tool reports a circular import or dependency cycle.

1. Trace the cycle from the error message. Most build tools report the full cycle path.
2. Break the cycle by one of:
   - **Extract shared types:** Move the shared type/interface to a separate module that both sides import.
   - **Dependency inversion:** Have one side accept the dependency via injection or a trait/interface rather than direct import.
   - **Merge modules:** If two modules are so intertwined they form a cycle, they may belong in the same module.
3. Build locally to confirm the cycle is broken.

### Fix 7: Out-of-Memory or Disk

**When:** Build process is killed by OOM or reports "no space left on device."

1. This is an infrastructure issue. Do not attempt a code fix.
2. Re-trigger the build in case it was transient.
3. If it persists, escalate. Possible mitigations (for the human to decide):
   - Increase CI runner resources.
   - Split the build into smaller jobs.
   - Add build caching to reduce work.

---

## When to Escalate

Escalate to a human (via the escalation format in `recovery-protocol.md`) when:

- The build error is in code you did not write and do not understand well enough to fix safely.
- The fix requires changing the CI toolchain version or CI configuration.
- Dependency version conflicts cannot be resolved without upgrading or replacing a package.
- The build failure is an out-of-memory or disk issue that cannot be fixed by code changes.
- Circular dependencies span multiple domains and the correct architectural fix is unclear (consult `kb/architecture/dependency-rules.md`).
- The build error suggests a fundamental architectural issue (e.g., a breaking change in a core library).
