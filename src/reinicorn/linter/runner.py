"""Lint runner — discovers and executes lint rules."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from reinicorn.linter.rules import BUILTIN_RULES

if TYPE_CHECKING:
    from pathlib import Path


def run_lints(project_root: Path) -> int:
    """Run all configured lint rules.  Returns 0 if no error-severity failures."""
    lint_config_path = project_root / "linters" / ".lint-config.json"

    if not lint_config_path.is_file():
        print(f"FATAL: Lint config not found at {lint_config_path}.")
        return 1

    try:
        config = json.loads(lint_config_path.read_text())
    except json.JSONDecodeError:
        print(f"FATAL: {lint_config_path} is not valid JSON.")
        return 1

    rules_config = config.get("rules", {})

    total = passed = failed_errors = failed_warnings = skipped = 0
    error_failures: list[str] = []
    warning_failures: list[str] = []

    # Built-in Python rules
    for rule_name, rule_cls in BUILTIN_RULES.items():
        rule_cfg = rules_config.get(rule_name)
        if rule_cfg is None:
            continue
        if not rule_cfg.get("enabled", False):
            skipped += 1
            continue

        severity = rule_cfg.get("severity", "warning")
        total += 1

        kwargs = {}
        if "max_days_stale" in rule_cfg:
            kwargs["max_days"] = rule_cfg["max_days_stale"]
        try:
            rule = rule_cls(**kwargs)
        except TypeError:
            rule = rule_cls()

        diagnostics = rule.run(project_root)

        if not diagnostics:
            passed += 1
            print(f"[PASS] {rule_name}")
        else:
            if severity == "error":
                failed_errors += 1
                error_failures.append(rule_name)
                print(f"[FAIL:ERROR] {rule_name}")
            else:
                failed_warnings += 1
                warning_failures.append(rule_name)
                print(f"[FAIL:WARNING] {rule_name}")
            for d in diagnostics:
                print(f"    {d}")
        print()

    # External .sh rules (extensibility)
    rules_dir = project_root / "linters" / "rules"
    if rules_dir.is_dir():
        for script in sorted(rules_dir.rglob("*.sh")):
            rel = script.relative_to(rules_dir)
            rule_name = str(rel).removesuffix(".sh")

            if rule_name in BUILTIN_RULES:
                continue

            rule_cfg = rules_config.get(rule_name)
            if rule_cfg is None or not rule_cfg.get("enabled", False):
                skipped += 1
                continue

            severity = rule_cfg.get("severity", "warning")
            total += 1

            try:
                result = subprocess.run(
                    [str(script), str(project_root)],
                    capture_output=True, text=True, check=False,
                )
            except Exception as e:
                print(f"[FAIL:ERROR] {rule_name}")
                print(f"    Error: {e}")
                failed_errors += 1
                error_failures.append(rule_name)
                continue

            if result.returncode == 0:
                passed += 1
                print(f"[PASS] {rule_name}")
            else:
                if severity == "error":
                    failed_errors += 1
                    error_failures.append(rule_name)
                    print(f"[FAIL:ERROR] {rule_name}")
                else:
                    failed_warnings += 1
                    warning_failures.append(rule_name)
                    print(f"[FAIL:WARNING] {rule_name}")
                for line in (result.stdout or "").strip().splitlines():
                    print(f"    {line}")
            print()

    # Summary
    print("========================================")
    print("Lint Summary")
    print("========================================")
    print(f"Total rules run: {total}")
    print(f"Passed:          {passed}")
    print(f"Errors:          {failed_errors}")
    print(f"Warnings:        {failed_warnings}")
    print(f"Skipped:         {skipped}")

    if error_failures:
        print()
        print("Error-severity failures (must fix):")
        for name in error_failures:
            print(f"  - {name}")

    if warning_failures:
        print()
        print("Warning-severity failures (should fix):")
        for name in warning_failures:
            print(f"  - {name}")

    print("========================================")

    return 1 if failed_errors > 0 else 0
