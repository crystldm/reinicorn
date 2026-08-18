## Reinicorn Integration

When working in a Reinicorn-managed repo, use the CLI to create and publish plans:

### Creating the plan file

```bash
rcorn plan create
```

This handles branch detection, ticket ID extraction from the branch name,
template population from `kb/{repo}/exec-plans/_template/`, and overlap
detection with other active branches.

### Populating the plan

After `rcorn plan create`, edit `kb/{repo}/exec-plans/active/{branch}/plan.md`
to fill in Goal, Acceptance Criteria, Approach, and Tasks using the task structure
defined above.

### Publishing

```bash
rcorn kb publish
```

### Checking status

```bash
rcorn plan status
```

### Gated docs (review lane)

Before building a plan on a spec (or any gated doc), check its status. A path
under `specs/drafts/` or a `**Status:** draft` / `**Status:** in-review` header
means the spec is **not approved** — it may still change under review. Stop and
ask the user for explicit confirmation before planning against an unapproved
spec. `rcorn review status` lists open reviews; `rcorn kb lint` warns when a
plan references a drafts-annex or in-review doc.
