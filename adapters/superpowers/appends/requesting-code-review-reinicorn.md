## Reinicorn PR Review

When reviewing PRs in a Reinicorn-managed repo, add these checks to the standard review:

### Golden principles check

Read `kb/{repo}/golden-principles.md`. For each principle, evaluate whether
the PR changes are consistent. Note violations with `file:line` references.

### Dependency rules check

Read `kb/{repo}/architecture/dependency-rules.md` if it exists. For each
changed file, determine its domain/layer and check imports against the matrix.

### Kb doc freshness

Based on changed files, check if kb docs need updating:
- New domain? Check for domain doc.
- Architecture shift? Flag dependency-rules or ARCHITECTURE.md.
- Changed behavior? Check if product specs reference it.
- Active exec plan? Check alignment.
