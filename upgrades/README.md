# Upgrade Notes

Per-version upgrade notes displayed by `rcorn update` when users
upgrade between versions. Each file covers one release.

## Naming Convention

Files must be named `v<version>.md` (e.g., `v0.2.0.md`).

## Format

```markdown
### v0.2.0

**Skills:**
- Added `foo-skill` — does X

**Hooks:**
- Updated `pre-push` to check Y

**Breaking changes:**
- Removed `bar` flag from `rcorn init`
```

Keep notes concise — users see them inline in terminal output.
The `_show_upgrade_notes()` function in `commands/update.py` displays
all notes between the user's current version and the new version.
