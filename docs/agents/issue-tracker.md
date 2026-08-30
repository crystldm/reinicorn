# Issue tracker

Tracker: GitHub Issues on `crystldm/reinicorn`. The `gh` CLI is available and
authenticated — use it, not the web UI.

## Triage labels

- `ready-for-agent` — triaged; an agent may pick it up. The only triage label
  in use for this pilot. More may be added later as need arises.

## What is, and isn't, a tracker item

- **Review-gated docs are NOT tracker items.** Specs live in the Reinicorn
  kb: create one with `rcorn spec create "<title>"`, read one with
  `rcorn spec show <slug> --full`. Don't file a spec as an issue.
- **Process artifacts ARE tracker items.** Tickets from `to-tickets` and
  wayfinder decision maps are GitHub issues, using GitHub's native
  blocking/sub-issue links (below). Record their URLs in the branch's plan
  doc — `rcorn plan create` if one doesn't exist yet.

## Wayfinding operations

- Map: `gh issue create --label wayfinder:map ...`.
- Ticket (child of the map): `gh issue create --parent <map-number> --label wayfinder:<type> ...`.
- Claim a ticket: `gh issue edit <number> --add-assignee @me`.
- Blocking edge: `gh issue edit <blocked-number> --add-blocked-by <blocker-number>`.
- Frontier query (open, unassigned, unblocked children of the map):

  ```bash
  gh issue list --state open --limit 500 --json number,title,assignees,blockedBy,parent \
    --jq '[.[] | select(.parent.number == <map-number>
      and (.assignees | length) == 0
      and ([.blockedBy.nodes[] | select(.state == "OPEN")] | length) == 0)]'
  ```
