---
name: update-superpowers
description: "Update forked superpowers skills from upstream plugin cache. Detects latest version, copies content, applies mechanical replacements, and reviews for Reinicorn-specific conventions."
---

# Update Forked Superpowers Skills

Update forked skills from the upstream superpowers plugin cache, apply mechanical replacements, review for correctness, and commit.

## Constants

- **Plugin cache:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/`
- **Skills directory:** `.agents/skills/`
- **Replacements config:** `.agents/skills/update-superpowers/replacements.yaml`
- **Non-forked skills (skip these):** `using-reinicorn`, `populate-agents-md`, `update-superpowers`

## Step 1: Detect versions

1. List directories under the plugin cache path. Each directory name is a version number (e.g. `5.0.6` — no `v` prefix). Sort by version number and pick the latest.
2. For each skill directory under `.agents/skills/` that is NOT in the skip list, read its `SKILL.md` frontmatter and extract the `upstream:` value (format: `superpowers/v<version>`). Strip the `superpowers/v` prefix to get the bare version number for comparison.
3. Report to the user: `Current: v<current> → Available: v<latest>`
4. If already current for all skills, report "Already up to date." and **stop**.

## Step 2: Identify changes

1. For each forked skill, diff the upstream `SKILL.md` (from the latest version directory, under `skills/<skill-name>/SKILL.md`) against the local fork. Strip the `upstream:` frontmatter line from the local copy before comparing.
2. Report which skills changed and the approximate diff size (lines added/removed).
3. Flag any new skills present in upstream but missing locally.
4. Flag any skills present locally (and not in the skip list) that were removed upstream.

## Step 3: Copy and patch

For each forked skill (not in the skip list):

1. **Preserve local trailers.** Before overwriting, scan the local `SKILL.md` for the first line matching `^## Reinicorn ` (heading starting with "Reinicorn "). If found, capture everything from that line to EOF as the *local trailer*. These are Reinicorn-specific additions that must survive upstream updates (e.g. `## Reinicorn Integration`, `## Reinicorn PR Review`). `tests/test_skill_copy.py` asserts the presence of specific trailer headings — do not drop them.
2. If the skill has content changes: copy the upstream `SKILL.md` content, replacing the local fork entirely.
3. Read `.agents/skills/update-superpowers/replacements.yaml`. Sort entries by length of `find` descending (longest first).
4. Apply each replacement as a literal string substitution across the file content.
5. Update the `upstream:` frontmatter tag to `superpowers/v<new-version>` for ALL forked skills, even those with no content changes — the version tag must stay in sync.
6. **Re-append the local trailer** (from step 1) to the end of the file, separated by a single blank line. Skip this for skills that had no trailer.

## Step 4: Agent review

Read each updated skill file and check for:

- Any remaining `docs/superpowers/` references the replacements missed.
- Paths that do not match Reinicorn kb conventions (`kb/<repo>/`).
- Structural changes worth flagging to the user (new sections, removed sections, changed gates).
- **Trailer integrity:** if the pre-update file had `## Reinicorn ` trailer section(s), verify they are still present post-update. Run `uv run pytest tests/test_skill_copy.py` as a sanity check — it asserts specific trailer headings exist in the installed package.

If new replacements are needed, add them to `replacements.yaml` (maintaining longest-first order) and re-apply all replacements to affected files.

Report all findings to the user.

## Step 5: Pause for approval

1. Run `git diff --stat` and show the output.
2. Highlight any files that had review findings from Step 4.
3. Ask the user to **approve**, **request changes**, or **abort**.
4. Do **NOT** proceed until the user explicitly approves.

## Step 6: Update metadata and commit

1. Edit `.agents/skills/ATTRIBUTION.md`: update the "Forked from" line to reflect the new version and set "Last updated" to today's date.
2. Commit all changed files with message: `chore: update forked superpowers skills <old-version> -> <new-version>`
