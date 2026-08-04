"""Reinicorn hooks install — install git hooks and editor hooks."""

from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

from reinicorn import console
from reinicorn.git import (
    GitError,
    classify_result,
    reinicorn_root,
    repo_root,
    report_failure,
    run_git,
)
from reinicorn.hooks_health import (
    HOOK_NAMES,
    MARKER,
    can_fall_through,
    is_stale_reins_hook,
    marker_reachable,
)

_SCRIPT_DEST = ".reinicorn/hooks"
_COPILOT_CONFIG = ".github/hooks/reinicorn.json"

# Editor PreToolUse hook scripts: (script filename, Claude Code tool matcher)
_EDITOR_HOOK_SCRIPTS = (
    ("enforce-doc-templates.sh", "Write|Edit"),
    ("block-raw-kb-git.sh", "Bash"),
)


def _claude_entry(script: str, matcher: str) -> dict:
    return {
        "matcher": matcher,
        "hooks": [{"type": "command", "command": f"{_SCRIPT_DEST}/{script}"}],
    }


def _cursor_entry(script: str, matcher: str) -> dict:
    return {"command": f"{_SCRIPT_DEST}/{script}", "matcher": matcher}


def _copilot_entry(script: str, _matcher: str) -> dict:
    return {"type": "command", "bash": f"{_SCRIPT_DEST}/{script}"}


def cmd_hooks_install() -> int:
    try:
        # --git-common-dir, not --git-dir: inside a linked worktree the latter
        # is .git/worktrees/<name>, where git never reads hooks.
        r = run_git("rev-parse", "--git-common-dir")
        git_dir = Path(r.stdout.strip()).resolve()
    except FileNotFoundError:
        console.error(
            "git was not found on PATH.\n"
            "  How to fix: install git, or add it to PATH."
        )
        return 1
    except GitError as e:
        # run_git raises on *any* nonzero exit, so only git's own "not a git
        # repository" earns that message. Dubious ownership, a corrupt repo,
        # and a broken config are different problems with different fixes.
        if classify_result(e) == "no-repo":
            console.error("Not inside a git repository.")
        else:
            report_failure("locate the git directory", e)
        return 1

    # --- Git hooks ---
    hooks_dest = git_dir / "hooks"
    hooks_dest.mkdir(parents=True, exist_ok=True)

    hooks_src = _find_asset_dir("hooks")
    if hooks_src is None:
        console.error("Cannot find Reinicorn hooks directory.")
        return 1

    installed = 0
    skipped = 0
    appended = 0
    already = 0
    replaced = 0
    failed = 0

    console.progress("Installing Reinicorn git hooks...")

    for hook_name in HOOK_NAMES:
        src_file = hooks_src / hook_name
        dest_file = hooks_dest / hook_name

        if not src_file.is_file():
            console.warn(f"SKIP: {hook_name} — source file not found at {src_file}")
            skipped += 1
            continue

        if not dest_file.is_file():
            shutil.copy2(src_file, dest_file)
            dest_file.chmod(dest_file.stat().st_mode | stat.S_IEXEC)
            console.success(f"INSTALLED: {hook_name} (new)")
            installed += 1
            continue

        existing = dest_file.read_text()
        # A verbatim copy of the current hook (fresh install, no marker) is
        # already installed — it must not fall through to the foreign-hook
        # checks, whose exit-guard refusal would misfire on our own template.
        if existing == src_file.read_text():
            console.warn(f"SKIP: {hook_name} — Reinicorn hooks already installed")
            already += 1
            skipped += 1
        # Stale check next: a reins-era hook damaged by the old append bug
        # carries the marker too, but its guard is dead and must be repaired.
        elif is_stale_reins_hook(existing):
            # The stale hook may carry user customizations the substring
            # match can't see — keep the old content recoverable.
            backup = dest_file.with_name(dest_file.name + ".bak")
            backup.write_text(existing)
            shutil.copy2(src_file, dest_file)
            dest_file.chmod(dest_file.stat().st_mode | stat.S_IEXEC)
            console.success(
                f"REPLACED: {hook_name} (stale reins-era hook; "
                f"backup: {backup.name})"
            )
            replaced += 1
        elif MARKER in existing:
            if marker_reachable(existing):
                console.warn(f"SKIP: {hook_name} — Reinicorn hooks already installed")
                already += 1
            else:
                console.error(
                    f"FAILED: {hook_name} — the Reinicorn section sits after an "
                    f"unconditional exit and never runs. "
                    f"Merge {src_file} into {dest_file} manually."
                )
                failed += 1
            skipped += 1
        elif not can_fall_through(existing):
            # Appending after an unconditional exit would be dead code —
            # claiming success here is how #24's repos lost their guard.
            console.error(
                f"FAILED: {hook_name} — existing hook ends in an unconditional "
                f"exit, so appended hooks would never run. "
                f"Merge {src_file} into {dest_file} manually."
            )
            failed += 1
        else:
            src_lines = src_file.read_text().splitlines()
            src_content = "\n".join(src_lines[1:]) if src_lines else ""
            candidate = f"{existing}\n{MARKER}\n\n{src_content}\n"
            # Verify before writing: the marker must actually be reachable
            # (a mid-script top-level exit slips past the last-line check).
            if not marker_reachable(candidate):
                console.error(
                    f"FAILED: {hook_name} — an unconditional exit in the "
                    f"existing hook would keep the appended hooks from running. "
                    f"Merge {src_file} into {dest_file} manually."
                )
                failed += 1
                continue
            dest_file.write_text(candidate)
            dest_file.chmod(dest_file.stat().st_mode | stat.S_IEXEC)
            console.success(f"APPENDED: {hook_name} (chained with existing hook)")
            appended += 1

    print()
    console.info(f"  Source:    {hooks_src}/")
    console.info(f"  Target:   {hooks_dest}/")
    console.success(f"  Installed: {installed}")
    if replaced:
        console.success(f"  Replaced:  {replaced}")
    if appended:
        console.success(f"  Appended:  {appended}")
    if skipped:
        console.warn(f"  Skipped:   {skipped}")
    if failed:
        console.error(f"  Failed:    {failed}")
    if installed == 0 and appended == 0 and replaced == 0 and failed == 0 and already > 0:
        console.info("hooks: already installed (no-op)")

    # --- Editor hooks (Claude Code, Cursor, Copilot) ---
    print()
    _install_editor_hooks()

    print()
    return 1 if failed else 0


def _install_editor_hooks() -> None:
    """Install editor PreToolUse hooks into .reinicorn/hooks/ and editor config files."""
    root = repo_root(quiet=True)
    if root is None:
        return

    editor_hooks_src = _find_asset_dir("editor-hooks")
    if editor_hooks_src is None:
        console.warn("Cannot find Reinicorn editor hooks — skipping.")
        return

    console.progress("Installing editor hooks...")

    dest_dir = root / _SCRIPT_DEST
    dest_dir.mkdir(parents=True, exist_ok=True)

    claude_entries: list[dict] = []
    cursor_entries: list[dict] = []
    copilot_entries: list[dict] = []

    for script, matcher in _EDITOR_HOOK_SCRIPTS:
        src = editor_hooks_src / script
        if not src.is_file():
            console.warn(f"SKIP: {script} — source not found")
            continue

        dest = dest_dir / script
        if dest.is_file() and dest.read_text() == src.read_text():
            console.warn(f"SKIP: {script} — already up to date")
        else:
            shutil.copy2(src, dest)
            dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
            console.success(f"INSTALLED: {script}")

        claude_entries.append(_claude_entry(script, matcher))
        cursor_entries.append(_cursor_entry(script, matcher))
        copilot_entries.append(_copilot_entry(script, matcher))

    # Merge hook entries into each editor's config
    _merge_claude_settings(root / ".claude" / "settings.json", claude_entries)
    _merge_cursor_settings(root / ".cursor" / "hooks.json", cursor_entries)
    _merge_copilot_settings(root / _COPILOT_CONFIG, copilot_entries)


def _merge_claude_settings(
    settings_path: Path, hook_entries: list[dict],
) -> None:
    """Merge hook entries into .claude/settings.json without clobbering existing config."""
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, ValueError):
            settings = {}
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings = {}

    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks
    pre_tool = hooks.get("PreToolUse")
    if not isinstance(pre_tool, list):
        pre_tool = []
        hooks["PreToolUse"] = pre_tool

    # Add entries that aren't already present (match by matcher)
    # NOTE: dedup is by matcher only — a future third script reusing an existing
    # matcher would be dropped; extend dedup (e.g. by command) if that ever happens.
    existing_matchers = {e.get("matcher") for e in pre_tool if isinstance(e, dict)}
    added = 0
    for entry in hook_entries:
        if entry.get("matcher") not in existing_matchers:
            pre_tool.append(entry)
            added += 1

    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    if added:
        console.success(f"Updated {settings_path} ({added} hook(s) added)")
    else:
        console.warn(f"{settings_path} — hooks already configured")


def _merge_cursor_settings(
    settings_path: Path, hook_entries: list[dict],
) -> None:
    """Merge hook entries into .cursor/hooks.json without clobbering existing config."""
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, ValueError):
            settings = {}
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings = {}

    settings.setdefault("version", 1)

    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks
    pre_tool = hooks.get("preToolUse")
    if not isinstance(pre_tool, list):
        pre_tool = []
        hooks["preToolUse"] = pre_tool

    # Add entries that aren't already present (match by command)
    existing_commands = {e.get("command") for e in pre_tool if isinstance(e, dict)}
    added = 0
    for entry in hook_entries:
        if entry.get("command") not in existing_commands:
            pre_tool.append(entry)
            added += 1

    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    if added:
        console.success(f"Updated {settings_path} ({added} hook(s) added)")
    else:
        console.warn(f"{settings_path} — hooks already configured")


def _merge_copilot_settings(
    settings_path: Path, hook_entries: list[dict],
) -> None:
    """Merge hook entries into reinicorn.json without clobbering existing config."""
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, ValueError):
            settings = {}
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings = {}

    settings.setdefault("version", 1)

    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks
    pre_tool = hooks.get("preToolUse")
    if not isinstance(pre_tool, list):
        pre_tool = []
        hooks["preToolUse"] = pre_tool

    # Add entries that aren't already present (match by bash field)
    existing_bash = {e.get("bash") for e in pre_tool if isinstance(e, dict)}
    added = 0
    for entry in hook_entries:
        if entry.get("bash") not in existing_bash:
            pre_tool.append(entry)
            added += 1

    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    if added:
        console.success(f"Updated {settings_path} ({added} hook(s) added)")
    else:
        console.warn(f"{settings_path} — hooks already configured")


def _find_asset_dir(name: str) -> Path | None:
    """Find a bundled asset directory by name."""
    r_root = reinicorn_root()
    if (r_root / name).is_dir():
        return r_root / name
    cwd_dir = Path.cwd() / name
    if cwd_dir.is_dir():
        return cwd_dir
    from reinicorn.assets import get_asset_path
    return get_asset_path(name)
