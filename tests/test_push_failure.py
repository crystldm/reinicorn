"""Tests for kb push-failure reporting.

Idea: kb/reinicorn/ideas/michael-biehl/
      rcorn-kb-publish-reports-any-post-retry-push-failure-as-conf.md

Classification itself lives in reinicorn.git and is tested in
tests/test_git_failure.py. What is asserted here is the kb-specific half:
which words the user sees and, crucially, which command they are sent to
next — the original bug's real cost was a "next" that looped forever.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from reinicorn.kb import explain_push_failure, push_next_steps, report_push_failure

AUTH_HTTPS = (
    "fatal: could not read Username for 'https://github.com': "
    "No such device or address\n"
)
AUTH_SSH = (
    "git@github.com: Permission denied (publickey).\n"
    "fatal: Could not read from remote repository.\n"
)
NON_FF = (
    " ! [rejected]        main -> main (fetch first)\n"
    "error: failed to push some refs to 'https://github.com/crystldm/reinicorn-kb.git'\n"
)
PROTECTED = (
    "remote: error: GH006: Protected branch update failed for refs/heads/main.\n"
)
DNS = (
    "fatal: unable to access 'https://github.com/crystldm/reinicorn-kb.git/': "
    "Could not resolve host: github.com\n"
)

HTTPS_URL = "https://github.com/crystldm/reinicorn-kb.git"
SSH_URL = "git@github.com:crystldm/reinicorn-kb.git"


def _push(stderr: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", "push"], 1, "", stderr)


# --------------------------------------------------------------------------
# push_next_steps — the half that made the original bug expensive
# --------------------------------------------------------------------------


def test_auth_next_step_is_the_protocol_fix(tmp_path: Path):
    with patch("reinicorn.kb.remote_url", return_value=HTTPS_URL), \
         patch("reinicorn.kb_remote.git_protocol_preference", return_value="ssh"):
        assert push_next_steps("auth", tmp_path) == [
            f"rcorn kb git remote set-url origin {SSH_URL}"
        ]


def test_auth_next_step_falls_back_to_gh_when_no_rewrite_helps(tmp_path: Path):
    with patch("reinicorn.kb.remote_url", return_value=SSH_URL), \
         patch("reinicorn.kb_remote.git_protocol_preference", return_value="ssh"):
        assert push_next_steps("auth", tmp_path) == ["gh auth status"]


def test_auth_next_step_never_suggests_retrying_the_failed_command(tmp_path: Path):
    """Retrying a push that failed on credentials loops forever — that loop is
    exactly what the reported bug cost a session."""
    with patch("reinicorn.kb.remote_url", return_value=HTTPS_URL), \
         patch("reinicorn.kb_remote.git_protocol_preference", return_value="ssh"):
        assert "rcorn kb publish" not in push_next_steps("auth", tmp_path)


def test_non_fast_forward_next_step_is_publish_again(tmp_path: Path):
    with patch("reinicorn.kb.remote_url", return_value=SSH_URL):
        assert push_next_steps("non-fast-forward", tmp_path) == ["rcorn kb publish"]


def test_protected_next_step_is_the_review_lane(tmp_path: Path):
    with patch("reinicorn.kb.remote_url", return_value=SSH_URL):
        assert push_next_steps("protected", tmp_path) == ["rcorn review start <draft>"]


def test_unknown_next_step_is_inspection_not_a_retry(tmp_path: Path):
    with patch("reinicorn.kb.remote_url", return_value=SSH_URL):
        assert push_next_steps("unknown", tmp_path) == ["rcorn kb git status"]


# --------------------------------------------------------------------------
# explain_push_failure — kb vocabulary on top of git's own words
# --------------------------------------------------------------------------


def test_explain_names_the_remote_and_its_protocol(tmp_path: Path):
    with patch("reinicorn.kb.remote_url", return_value=HTTPS_URL):
        body = "\n".join(explain_push_failure(_push(AUTH_HTTPS), tmp_path))
    assert f"remote: {HTTPS_URL} (https)" in body
    assert "could not read Username" in body
    assert "conflicting changes" not in body


def test_explain_keeps_the_conflict_wording_for_a_real_conflict(tmp_path: Path):
    with patch("reinicorn.kb.remote_url", return_value=SSH_URL):
        body = "\n".join(explain_push_failure(_push(NON_FF), tmp_path))
    assert "kb has conflicting changes" in body
    assert "Resolve any conflicts in kb/" in body


def test_explain_says_protected_for_a_protected_branch(tmp_path: Path):
    with patch("reinicorn.kb.remote_url", return_value=SSH_URL):
        body = "\n".join(explain_push_failure(_push(PROTECTED), tmp_path))
    assert "protected" in body.lower()
    assert "review lane" in body
    assert "conflicting changes" not in body


def test_explain_of_an_unknown_failure_shows_git_and_guesses_nothing(tmp_path: Path):
    with patch("reinicorn.kb.remote_url", return_value=SSH_URL):
        body = "\n".join(explain_push_failure(_push(DNS), tmp_path))
    assert "Could not resolve host: github.com" in body
    assert "conflicting changes" not in body
    assert "authentication" not in body.lower()


def test_explain_handles_a_missing_remote(tmp_path: Path):
    with patch("reinicorn.kb.remote_url", return_value=""):
        body = "\n".join(explain_push_failure(_push(DNS), tmp_path))
    assert "(none)" in body


# --------------------------------------------------------------------------
# report_push_failure
# --------------------------------------------------------------------------


def test_report_prints_the_diagnosis_and_the_next_step(tmp_path: Path, capsys):
    with patch("reinicorn.kb.remote_url", return_value=HTTPS_URL), \
         patch("reinicorn.kb_remote.git_protocol_preference", return_value="ssh"):
        kind = report_push_failure(_push(AUTH_HTTPS), tmp_path)
    out = capsys.readouterr().out
    assert kind == "auth"
    assert out.startswith("error: Could not push kb main")
    assert f"next: rcorn kb git remote set-url origin {SSH_URL}" in out


def test_report_of_a_multiline_failure_keeps_every_line(tmp_path: Path, capsys):
    with patch("reinicorn.kb.remote_url", return_value=SSH_URL):
        report_push_failure(_push(AUTH_SSH), tmp_path)
    out = capsys.readouterr().out
    for line in AUTH_SSH.strip().splitlines():
        assert line in out


# --------------------------------------------------------------------------
# Wiring: both lanes must report the same way
# --------------------------------------------------------------------------


def test_publish_reports_an_auth_failure_as_auth(
    submodule_repo: Path, monkeypatch, capsys,
):
    from reinicorn.commands.publish import cmd_publish

    monkeypatch.chdir(submodule_repo)
    with patch(
        "reinicorn.commands.publish.push_main_with_retry", return_value=_push(AUTH_HTTPS),
    ), patch("reinicorn.commands.publish.can_publish", return_value=True):
        assert cmd_publish() == 1
    out = capsys.readouterr().out
    assert "conflicting changes" not in out
    assert "authentication" in out.lower()


def test_review_push_reports_an_auth_failure_once(submodule_repo: Path, capsys):
    """The lane prints the diagnosis exactly once — the decorator must not
    repeat what _push_kb_main already reported in full."""
    from reinicorn.commands.review import _AlreadyReportedError, _push_kb_main

    with patch(
        "reinicorn.commands.review.push_main_with_retry", return_value=_push(AUTH_HTTPS),
    ):
        try:
            _push_kb_main(submodule_repo / "kb")
        except _AlreadyReportedError:
            pass
        else:  # pragma: no cover - the lane must still abort
            raise AssertionError("_push_kb_main must raise on a failed push")
    out = capsys.readouterr().out
    assert out.count("Could not push kb main") == 1
    assert "authentication" in out.lower()


def test_review_decorator_does_not_repeat_an_already_reported_failure(capsys):
    from reinicorn.commands.review import _AlreadyReportedError, _surfacing_errors

    @_surfacing_errors
    def failing() -> int:
        raise _AlreadyReportedError("kb push failed")

    assert failing() == 1
    assert capsys.readouterr().out == ""


def test_review_decorator_surfaces_a_git_error_through_the_seam(capsys):
    from reinicorn.commands.review import _surfacing_errors
    from reinicorn.git import GitError

    @_surfacing_errors
    def failing() -> int:
        raise GitError(1, ["git", "clone"], "", DNS)

    assert failing() == 1
    out = capsys.readouterr().out
    assert "Could not complete the review operation" in out
    assert "Could not resolve host: github.com" in out
