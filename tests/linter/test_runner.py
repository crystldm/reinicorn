"""Tests for the lint runner."""

from __future__ import annotations

import json
from pathlib import Path

from reinicorn.linter.runner import run_lints

CROSS_LINKS = "kb/cross-links"


def _write_config(root: Path, rules: dict) -> None:
    """Write linters/.lint-config.json with exactly the given rules."""
    linters = root / "linters"
    linters.mkdir(parents=True, exist_ok=True)
    (linters / ".lint-config.json").write_text(json.dumps({"rules": rules}))


def _write_rule_script(
    root: Path, name: str, body: str, *, executable: bool = True
) -> Path:
    """Drop an external .sh rule at linters/rules/<name>.sh.

    The runner derives the rule name from the path relative to rules/, so
    name "custom/ok" becomes rule "custom/ok".
    """
    script = root / "linters" / "rules" / f"{name}.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body)
    if executable:
        script.chmod(0o755)
    return script


def _break_cross_links(root: Path) -> None:
    """Give the cross-links rule something to complain about."""
    (root / "AGENTS.md").write_text("# Agents\n\nSee [missing](nope.md).\n")


def test_runner_no_config(tmp_path: Path, capsys):
    result = run_lints(tmp_path)
    assert result == 1
    assert "FATAL" in capsys.readouterr().out


def test_runner_invalid_json(tmp_path: Path, capsys):
    linters = tmp_path / "linters"
    linters.mkdir()
    (linters / ".lint-config.json").write_text("not json")
    result = run_lints(tmp_path)
    assert result == 1


def test_runner_all_pass(kb_repo: Path, capsys):
    # Create an AGENTS.md with no broken links
    (kb_repo / "AGENTS.md").write_text("# Agents\n\nNo links here.\n")

    run_lints(kb_repo)
    out = capsys.readouterr().out
    assert "Lint Summary" in out
    # cross-links should pass (no broken links), plan-structure should pass (no active plans)
    assert "PASS" in out


# --- built-in rule handling ----------------------------------------------


def test_disabled_builtin_rule_counts_as_skipped(tmp_path: Path, capsys):
    _write_config(tmp_path, {CROSS_LINKS: {"enabled": False}})

    assert run_lints(tmp_path) == 0
    out = capsys.readouterr().out
    assert "Skipped:         1" in out
    assert "Total rules run: 0" in out


def test_unconfigured_builtin_rule_is_ignored(tmp_path: Path, capsys):
    """A rule absent from the config is neither run nor counted as skipped."""
    _write_config(tmp_path, {})

    assert run_lints(tmp_path) == 0
    out = capsys.readouterr().out
    assert "Total rules run: 0" in out
    assert "Skipped:         0" in out


def test_rule_rejecting_max_days_falls_back_to_no_kwargs(tmp_path: Path, capsys):
    """cross-links takes no kwargs; max_days_stale must not blow up the run.

    The runner passes max_days= when the config carries max_days_stale and
    retries bare on TypeError.
    """
    _write_config(
        tmp_path,
        {CROSS_LINKS: {"enabled": True, "severity": "error", "max_days_stale": 5}},
    )

    assert run_lints(tmp_path) == 0
    assert f"[PASS] {CROSS_LINKS}" in capsys.readouterr().out


def test_builtin_failure_at_error_severity(tmp_path: Path, capsys):
    _write_config(tmp_path, {CROSS_LINKS: {"enabled": True, "severity": "error"}})
    _break_cross_links(tmp_path)

    assert run_lints(tmp_path) == 1
    out = capsys.readouterr().out
    assert f"[FAIL:ERROR] {CROSS_LINKS}" in out
    assert "Broken link to 'nope.md'" in out
    assert "Errors:          1" in out
    assert "Error-severity failures (must fix):" in out
    assert f"  - {CROSS_LINKS}" in out


def test_builtin_failure_at_warning_severity_does_not_fail_the_run(
    tmp_path: Path, capsys
):
    _write_config(tmp_path, {CROSS_LINKS: {"enabled": True, "severity": "warning"}})
    _break_cross_links(tmp_path)

    assert run_lints(tmp_path) == 0
    out = capsys.readouterr().out
    assert f"[FAIL:WARNING] {CROSS_LINKS}" in out
    assert "Warnings:        1" in out
    assert "Warning-severity failures (should fix):" in out


def test_severity_defaults_to_warning(tmp_path: Path, capsys):
    """No severity key means a failure must not fail the run."""
    _write_config(tmp_path, {CROSS_LINKS: {"enabled": True}})
    _break_cross_links(tmp_path)

    assert run_lints(tmp_path) == 0
    assert f"[FAIL:WARNING] {CROSS_LINKS}" in capsys.readouterr().out


# --- external .sh rules ---------------------------------------------------
#
# This whole loop was dead to the suite: the kb_repo fixture creates
# linters/ but never linters/rules/, so the is_dir() guard was always False.
# The real repo ships kb/provenance.sh and scripts/shellcheck.sh here.


def test_external_script_passing(tmp_path: Path, capsys):
    _write_config(tmp_path, {"custom/ok": {"enabled": True, "severity": "error"}})
    _write_rule_script(tmp_path, "custom/ok", "#!/bin/sh\nexit 0\n")

    assert run_lints(tmp_path) == 0
    out = capsys.readouterr().out
    assert "[PASS] custom/ok" in out
    assert "Total rules run: 1" in out


def test_external_script_failing_at_error_severity(tmp_path: Path, capsys):
    _write_config(tmp_path, {"custom/bad": {"enabled": True, "severity": "error"}})
    _write_rule_script(
        tmp_path, "custom/bad", "#!/bin/sh\necho 'something is wrong'\nexit 1\n"
    )

    assert run_lints(tmp_path) == 1
    out = capsys.readouterr().out
    assert "[FAIL:ERROR] custom/bad" in out
    assert "something is wrong" in out
    assert "Error-severity failures (must fix):" in out


def test_external_script_failing_at_warning_severity(tmp_path: Path, capsys):
    _write_config(tmp_path, {"custom/bad": {"enabled": True, "severity": "warning"}})
    _write_rule_script(tmp_path, "custom/bad", "#!/bin/sh\necho 'heads up'\nexit 1\n")

    assert run_lints(tmp_path) == 0
    out = capsys.readouterr().out
    assert "[FAIL:WARNING] custom/bad" in out
    assert "heads up" in out
    assert "Warning-severity failures (should fix):" in out


def test_external_script_receives_project_root(tmp_path: Path, capsys):
    """The runner passes the project root as argv[1]."""
    _write_config(tmp_path, {"custom/echo": {"enabled": True, "severity": "warning"}})
    _write_rule_script(tmp_path, "custom/echo", '#!/bin/sh\necho "root=$1"\nexit 1\n')

    run_lints(tmp_path)
    assert f"root={tmp_path}" in capsys.readouterr().out


def test_external_script_shadowing_a_builtin_is_ignored(tmp_path: Path, capsys):
    """A .sh named after a built-in must not shadow or double-run it."""
    _write_config(tmp_path, {CROSS_LINKS: {"enabled": True, "severity": "error"}})
    _write_rule_script(tmp_path, CROSS_LINKS, "#!/bin/sh\nexit 1\n")

    # The built-in runs and passes; the shadowing script is skipped entirely,
    # so the run stays green and only one rule is counted.
    assert run_lints(tmp_path) == 0
    out = capsys.readouterr().out
    assert "Total rules run: 1" in out
    assert "Skipped:         0" in out


def test_unconfigured_external_script_counts_as_skipped(tmp_path: Path, capsys):
    _write_config(tmp_path, {})
    _write_rule_script(tmp_path, "custom/orphan", "#!/bin/sh\nexit 0\n")

    assert run_lints(tmp_path) == 0
    assert "Skipped:         1" in capsys.readouterr().out


def test_disabled_external_script_counts_as_skipped(tmp_path: Path, capsys):
    _write_config(tmp_path, {"custom/off": {"enabled": False}})
    _write_rule_script(tmp_path, "custom/off", "#!/bin/sh\nexit 0\n")

    assert run_lints(tmp_path) == 0
    assert "Skipped:         1" in capsys.readouterr().out


def test_non_executable_external_script_is_reported_as_an_error(
    tmp_path: Path, capsys
):
    """A rule script without the exec bit must be reported, not crash the run."""
    _write_config(tmp_path, {"custom/noexec": {"enabled": True, "severity": "error"}})
    _write_rule_script(
        tmp_path, "custom/noexec", "#!/bin/sh\nexit 0\n", executable=False
    )

    assert run_lints(tmp_path) == 1
    out = capsys.readouterr().out
    assert "[FAIL:ERROR] custom/noexec" in out
    assert "Error:" in out
    assert "Error-severity failures (must fix):" in out
