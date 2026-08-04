"""Tests for hook-script classification (stale reins-era, reachability)."""

from __future__ import annotations

from pathlib import Path

from reinicorn.hooks_health import (
    MARKER,
    can_fall_through,
    hook_issues,
    is_stale_reins_hook,
    marker_reachable,
)

REINS_PRE_PUSH = (
    "#!/usr/bin/env bash\n"
    "if command -v reins &>/dev/null; then\n"
    "    reins _pre-push\n"
    "    exit $?\n"
    "fi\n"
    "\n"
    "exit 0\n"
)

RCORN_PRE_PUSH = (
    "#!/usr/bin/env bash\n"
    "if command -v rcorn &>/dev/null; then\n"
    "    rcorn _pre-push\n"
    "    exit $?\n"
    "fi\n"
    "\n"
    "exit 0\n"
)

FOREIGN_EXITING = "#!/bin/sh\necho lint\nexit 0\n"
FOREIGN_FALLTHROUGH = "#!/bin/sh\necho lint\n"


# --- is_stale_reins_hook ---


def test_reins_delegation_is_stale():
    assert is_stale_reins_hook(REINS_PRE_PUSH) is True


def test_old_reins_marker_is_stale():
    text = "#!/bin/sh\n# --- reins hooks below ---\necho x\n"
    assert is_stale_reins_hook(text) is True


def test_current_rcorn_hook_is_not_stale():
    assert is_stale_reins_hook(RCORN_PRE_PUSH) is False


def test_foreign_hook_is_not_stale():
    assert is_stale_reins_hook(FOREIGN_EXITING) is False


def test_damaged_append_shape_is_stale():
    """A reins hook that got the current hook appended after its exit 0 is
    still stale — the append is unreachable (issue #24)."""
    damaged = REINS_PRE_PUSH + f"\n{MARKER}\n\n{RCORN_PRE_PUSH}"
    assert is_stale_reins_hook(damaged) is True


# --- can_fall_through ---


def test_trailing_unconditional_exit_cannot_fall_through():
    assert can_fall_through(FOREIGN_EXITING) is False


def test_trailing_exit_status_cannot_fall_through():
    assert can_fall_through("#!/bin/sh\nsome-linter\nexit $?\n") is False


def test_trailing_compound_exit_cannot_fall_through():
    """`some-linter; exit $?` on one line is still an unconditional exit."""
    assert can_fall_through("#!/bin/sh\nsome-linter; exit $?\n") is False


def test_indented_compound_exit_falls_through():
    text = "#!/bin/sh\nif fail; then\n    log; exit 1\nfi\n"
    assert can_fall_through(text) is True


def test_plain_script_falls_through():
    assert can_fall_through(FOREIGN_FALLTHROUGH) is True


def test_indented_conditional_exit_falls_through():
    text = "#!/bin/sh\nif fail; then\n    exit 1\nfi\n"
    assert can_fall_through(text) is True


def test_comments_and_blanks_ignored():
    text = "#!/bin/sh\necho x\nexit 0\n# trailing comment\n\n"
    assert can_fall_through(text) is False


# --- marker_reachable ---


def test_marker_absent_is_not_reachable():
    assert marker_reachable(FOREIGN_FALLTHROUGH) is False


def test_marker_after_fall_through_is_reachable():
    text = f"{FOREIGN_FALLTHROUGH}\n{MARKER}\n\nrcorn _pre-push\n"
    assert marker_reachable(text) is True


def test_marker_after_unconditional_exit_is_unreachable():
    text = f"{FOREIGN_EXITING}\n{MARKER}\n\nrcorn _pre-push\n"
    assert marker_reachable(text) is False


def test_marker_after_compound_exit_is_unreachable():
    text = f"#!/bin/sh\nsome-linter; exit $?\n\n{MARKER}\n\nrcorn _pre-push\n"
    assert marker_reachable(text) is False


def test_marker_after_compound_exit_in_comment_is_reachable():
    """A comment mentioning `; exit 0` must not count as an exit."""
    text = f"#!/bin/sh\n# cleanup; exit 0\necho x\n\n{MARKER}\n\nrcorn _pre-push\n"
    assert marker_reachable(text) is True


def test_marker_after_indented_exit_is_reachable():
    text = (
        "#!/bin/sh\nif fail; then\n    exit 1\nfi\n"
        f"\n{MARKER}\n\nrcorn _pre-push\n"
    )
    assert marker_reachable(text) is True


# --- hook_issues ---


def test_hook_issues_reports_stale_and_unreachable(tmp_path: Path):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "pre-push").write_text(REINS_PRE_PUSH)
    (hooks / "post-merge").write_text(
        f"{FOREIGN_EXITING}\n{MARKER}\n\nrcorn _post-merge\n"
    )
    (hooks / "post-checkout").write_text(RCORN_PRE_PUSH)  # healthy

    issues = hook_issues(hooks)

    problems = {i.name: i.problem for i in issues}
    assert set(problems) == {"pre-push", "post-merge"}
    assert "stale" in problems["pre-push"]
    assert "unreachable" in problems["post-merge"]


def test_hook_issues_empty_for_missing_dir(tmp_path: Path):
    assert hook_issues(tmp_path / "nope") == []
