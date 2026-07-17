"""Smoke tests for the noun-first CLI shape."""
from __future__ import annotations

import subprocess
import sys


def _rcorn(*args, expect_returncode=0):
    result = subprocess.run(
        [sys.executable, "-m", "reinicorn", *args],
        capture_output=True, text=True,
    )
    assert result.returncode == expect_returncode, (
        f"rcorn {' '.join(args)} failed: {result.stderr}"
    )
    return result


def test_top_level_help_lists_noun_groups():
    r = _rcorn("--help")
    out = r.stdout
    for noun in ("spec", "prd", "debt", "idea", "plan",
                 "retro", "principle", "review", "kb", "mode",
                 "init", "hooks", "update", "feedback"):
        assert noun in out, f"missing noun group: {noun}"


def test_update_help_describes_only_reinicorn_managed_assets():
    r = _rcorn("--help")
    normalized_help = " ".join(r.stdout.split())

    assert "AGENTS.md" not in r.stdout
    assert (
        "Re-sync bundled files (skills, hooks, linters) to the installed Reinicorn version"
        in normalized_help
    )


def test_old_top_level_commands_are_removed():
    for old in ("sync", "publish", "lint", "status",
                "enable", "disable", "incognito", "doc", "kb-git", "design"):
        r = _rcorn(old, expect_returncode=2)
        # Don't pin to a specific argparse wording — exit 2 with any non-empty
        # stderr is enough to confirm the command is rejected.
        assert r.stderr.strip(), (
            f"expected non-empty stderr for removed command {old!r}"
        )


def test_kb_subcommands_listed():
    r = _rcorn("kb", "--help")
    for verb in ("sync", "publish", "status", "lint",
                 "list", "remove-scope", "git"):
        assert verb in r.stdout, f"missing kb verb: {verb}"


def test_mode_subcommands_listed():
    r = _rcorn("mode", "--help")
    for verb in ("enable", "disable", "incognito", "status"):
        assert verb in r.stdout, f"missing mode verb: {verb}"


def test_spec_subcommands_listed():
    r = _rcorn("spec", "--help")
    assert "create" in r.stdout
    assert "show" in r.stdout
    assert "list" in r.stdout


def test_prd_subcommands_listed():
    r = _rcorn("prd", "--help")
    assert "create" in r.stdout
    assert "show" in r.stdout
    assert "list" in r.stdout


def test_debt_subcommands_listed():
    r = _rcorn("debt", "--help")
    assert "create" in r.stdout
    assert "show" in r.stdout
    assert "list" in r.stdout


def test_idea_subcommands_listed():
    r = _rcorn("idea", "--help")
    assert "create" in r.stdout
    assert "show" in r.stdout
    assert "list" in r.stdout


def test_plan_subcommands_listed():
    r = _rcorn("plan", "--help")
    for verb in ("create", "status", "complete", "show"):
        assert verb in r.stdout, f"missing plan verb: {verb}"


def test_review_subcommands_listed():
    r = _rcorn("review", "--help")
    for verb in ("start", "push", "merge", "cancel", "link", "status", "setup"):
        assert verb in r.stdout, f"missing review verb: {verb}"


def test_retro_subcommands_listed():
    r = _rcorn("retro", "--help")
    assert "create" in r.stdout
    assert "show" in r.stdout


def test_version_uses_rcorn_name():
    r = _rcorn("--version")
    assert r.stdout.startswith("rcorn ")
