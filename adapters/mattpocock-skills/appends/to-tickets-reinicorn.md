## Reinicorn

GitHub issues are process artifacts; the kb's pointer to them is the
branch's plan doc. After publishing the tickets, record their URLs there:

```bash
rcorn plan status          # is there a plan doc for this branch?
rcorn plan create          # if not, create one
```

Then add the issue links to the plan's task list and `rcorn kb publish`,
so the plan doc stays the one place that says which tickets this branch
covers.
