"""Tests for kb push-failure classification and reporting.

Idea: kb/reinicorn/ideas/michael-biehl/
      rcorn-kb-publish-reports-any-post-retry-push-failure-as-conf.md

Every non-zero push used to be reported as "kb has conflicting changes", which
sent people to resolve conflicts in a clean tree and suggested the command that
had just failed. Classify on git's stderr instead, and when the class is not
recognized, print git verbatim rather than substituting a guess.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from reinicorn.kb import classify_push_failure, report_push_failure

AUTH_HTTPS = (
    "fatal: could not read Username for 'https://github.com': "
    "No such device or address\n"
)
AUTH_SSH = (
    "git@github.com: Permission denied (publickey).\n"
    "fatal: Could not read from remote repository.\n"
)
AUTH_PAT = (
    "remote: Support for password authentication was removed.\n"
    "fatal: Authentication failed for 'https://github.com/crystldm/reinicorn-kb.git/'\n"
)
NON_FF = (
    " ! [rejected]        main -> main (fetch first)\n"
    "error: failed to push some refs to 'https://github.com/crystldm/reinicorn-kb.git'\n"
    "hint: Updates were rejected because the remote contains work that you do not\n"
    "hint: have locally.\n"
)
NON_FF_FORCED = " ! [rejected]        main -> main (non-fast-forward)\n"
PROTECTED = (
    "remote: error: GH006: Protected branch update failed for refs/heads/main.\n"
    "remote: error: Changes must be made through a pull request.\n"
)
DNS = (
    "fatal: unable to access 'https://github.com/crystldm/reinicorn-kb.git/': "
    "Could not resolve host: github.com\n"
)


def _push(stderr: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", "push"], 1, "", stderr)


# --------------------------------------------------------------------------
# classify_push_failure
# --------------------------------------------------------------------------


def test_classifies_https_credential_prompt_as_auth():
    assert classify_push_failure(AUTH_HTTPS) == "auth"


def test_classifies_ssh_publickey_rejection_as_auth():
    assert classify_push_failure(AUTH_SSH) == "auth"


def test_classifies_authentication_failed_as_auth():
    assert classify_push_failure(AUTH_PAT) == "auth"


def test_classifies_fetch_first_as_non_fast_forward():
    assert classify_push_failure(NON_FF) == "non-fast-forward"


def test_classifies_non_fast_forward_as_non_fast_forward():
    assert classify_push_failure(NON_FF_FORCED) == "non-fast-forward"


def test_classifies_gh006_as_protected():
    assert classify_push_failure(PROTECTED) == "protected"


def test_classifies_protected_branch_wording_as_protected():
    assert classify_push_failure("remote: error: protected branch hook declined\n") == (
        "protected"
    )


def test_classifies_anything_else_as_unknown():
    assert classify_push_failure(DNS) == "unknown"


def test_classifies_empty_stderr_as_unknown():
    assert classify_push_failure("") == "unknown"


# --------------------------------------------------------------------------
# report_push_failure
# --------------------------------------------------------------------------


def test_auth_report_names_the_remote_and_protocol(tmp_path: Path, capsys):
    with patch(
        "reinicorn.kb.remote_url",
        return_value="https://github.com/crystldm/reinicorn-kb.git",
    ), patch("reinicorn.kb_remote.git_protocol_preference", return_value="ssh"):
        report_push_failure(_push(AUTH_HTTPS), tmp_path)
    out = capsys.readouterr().out
    assert "authenticat" in out.lower()
    assert "conflicting changes" not in out
    assert "https://github.com/crystldm/reinicorn-kb.git" in out
    assert "https" in out
    # The concrete escape hatch, pointed at the protocol the user actually uses.
    assert (
        "next: rcorn kb git remote set-url origin "
        "git@github.com:crystldm/reinicorn-kb.git" in out
    )


def test_auth_report_without_a_protocol_rewrite_to_offer(tmp_path: Path, capsys):
    """An ssh remote that fails auth has no URL fix — send them to gh instead."""
    with patch(
        "reinicorn.kb.remote_url",
        return_value="git@github.com:crystldm/reinicorn-kb.git",
    ), patch("reinicorn.kb_remote.git_protocol_preference", return_value="ssh"):
        report_push_failure(_push(AUTH_SSH), tmp_path)
    out = capsys.readouterr().out
    assert "(ssh)" in out
    assert "remote set-url" not in out
    assert "next: gh auth status" in out


def test_non_fast_forward_report_keeps_the_conflict_message(tmp_path: Path, capsys):
    with patch("reinicorn.kb.remote_url", return_value="git@github.com:o/r.git"):
        report_push_failure(_push(NON_FF), tmp_path)
    out = capsys.readouterr().out
    assert "conflicting changes" in out
    assert "next: rcorn kb publish" in out


def test_protected_report_points_at_the_review_lane(tmp_path: Path, capsys):
    with patch("reinicorn.kb.remote_url", return_value="git@github.com:o/r.git"):
        report_push_failure(_push(PROTECTED), tmp_path)
    out = capsys.readouterr().out
    assert "protected" in out.lower()
    assert "review" in out.lower()
    assert "conflicting changes" not in out


def test_unknown_report_prints_git_stderr_verbatim(tmp_path: Path, capsys):
    with patch("reinicorn.kb.remote_url", return_value="git@github.com:o/r.git"):
        report_push_failure(_push(DNS), tmp_path)
    out = capsys.readouterr().out
    assert DNS.strip() in out
    assert "conflicting changes" not in out
    assert "next: rcorn kb git status" in out


def test_unknown_report_with_empty_stderr_still_explains(tmp_path: Path, capsys):
    with patch("reinicorn.kb.remote_url", return_value="git@github.com:o/r.git"):
        report_push_failure(_push(""), tmp_path)
    out = capsys.readouterr().out
    assert "error:" in out
    assert "conflicting changes" not in out


# --------------------------------------------------------------------------
# Wiring: both lanes must report the same way
# --------------------------------------------------------------------------


def test_publish_reports_an_auth_failure_as_auth(submodule_repo: Path, monkeypatch, capsys):
    from reinicorn.commands.publish import cmd_publish

    monkeypatch.chdir(submodule_repo)
    with patch(
        "reinicorn.commands.publish.push_main_with_retry", return_value=_push(AUTH_HTTPS),
    ), patch("reinicorn.commands.publish.can_publish", return_value=True):
        assert cmd_publish() == 1
    out = capsys.readouterr().out
    assert "conflicting changes" not in out
    assert "authenticat" in out.lower()


def test_review_push_reports_an_auth_failure_as_auth(submodule_repo: Path, capsys):
    from reinicorn.commands.review import _push_kb_main

    with patch(
        "reinicorn.commands.review.push_main_with_retry", return_value=_push(AUTH_HTTPS),
    ):
        try:
            _push_kb_main(submodule_repo / "kb")
        except RuntimeError:
            pass
        else:  # pragma: no cover - the lane must still abort
            raise AssertionError("_push_kb_main must raise on a failed push")
    out = capsys.readouterr().out
    assert "authenticat" in out.lower()
    assert "conflicting changes" not in out
