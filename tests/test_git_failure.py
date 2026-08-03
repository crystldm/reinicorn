"""Tests for the single git-failure→message seam in reinicorn.git.

Every git failure the user is meant to hear about is converted to text in
exactly one place. Before this, six modules each invented their own shape and
one of them (kb publish) substituted a guess for git's actual complaint.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from reinicorn.git import (
    GitError,
    classify_failure,
    classify_result,
    explain_failure,
    report_failure,
    run_git,
    url_protocol,
)

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


def _result(stderr: str, returncode: int = 1) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", "push"], returncode, "", stderr)


def _error(stderr: str, returncode: int = 1) -> GitError:
    return GitError(returncode, ["git", "push"], "", stderr)


# --------------------------------------------------------------------------
# GitError
# --------------------------------------------------------------------------


def test_git_error_is_a_called_process_error():
    """The documented contract (review.py) says local git ops raise
    CalledProcessError; every existing handler must keep working."""
    assert issubclass(GitError, subprocess.CalledProcessError)


def test_git_error_carries_cmd_returncode_and_stderr():
    e = _error("boom\n", returncode=128)
    assert e.returncode == 128
    assert e.cmd == ["git", "push"]
    assert e.stderr == "boom\n"


def test_run_git_raises_git_error_on_failure(tmp_path: Path):
    with pytest.raises(GitError) as excinfo:
        run_git("rev-parse", "--verify", "refs/heads/nope", cwd=tmp_path)
    assert excinfo.value.returncode != 0
    assert excinfo.value.stderr


def test_run_git_error_is_catchable_as_called_process_error(tmp_path: Path):
    with pytest.raises(subprocess.CalledProcessError):
        run_git("rev-parse", "--verify", "refs/heads/nope", cwd=tmp_path)


def test_run_git_check_false_still_returns_a_result(tmp_path: Path):
    r = run_git("rev-parse", "--verify", "refs/heads/nope",
                check=False, cwd=tmp_path)
    assert r.returncode != 0


# --------------------------------------------------------------------------
# classify_failure
# --------------------------------------------------------------------------


@pytest.mark.parametrize("stderr", [AUTH_HTTPS, AUTH_SSH, AUTH_PAT])
def test_classifies_credential_failures_as_auth(stderr: str):
    assert classify_failure(stderr) == "auth"


@pytest.mark.parametrize("stderr", [NON_FF, NON_FF_FORCED])
def test_classifies_rejected_pushes_as_non_fast_forward(stderr: str):
    assert classify_failure(stderr) == "non-fast-forward"


def test_classifies_gh006_as_protected():
    assert classify_failure(PROTECTED) == "protected"


def test_classifies_protected_branch_wording_as_protected():
    assert classify_failure("remote: error: protected branch hook declined\n") == (
        "protected"
    )


def test_classifies_not_a_git_repository_as_no_repo():
    assert classify_failure(
        "fatal: not a git repository (or any of the parent directories): .git\n"
    ) == "no-repo"


def test_classifies_anything_else_as_unknown():
    assert classify_failure(DNS) == "unknown"


def test_classifies_empty_stderr_as_unknown():
    assert classify_failure("") == "unknown"


def test_auth_wins_over_a_rejected_ref():
    """A credential failure can be reported alongside a rejected ref; auth is
    the diagnosis that changes what the user should do next."""
    assert classify_failure(NON_FF + AUTH_HTTPS) == "auth"


def test_classify_result_accepts_a_completed_process():
    assert classify_result(_result(AUTH_HTTPS)) == "auth"


def test_classify_result_accepts_a_git_error():
    assert classify_result(_error(PROTECTED)) == "protected"


def test_classify_result_tolerates_missing_stderr():
    """capture=False leaves stderr None; classification must not crash."""
    assert classify_result(subprocess.CompletedProcess(["git"], 1, None, None)) == (
        "unknown"
    )


# --------------------------------------------------------------------------
# url_protocol
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/o/r.git", "https"),
        ("http://example.invalid/r.git", "https"),
        ("git@github.com:o/r.git", "ssh"),
        ("ssh://git@github.com/o/r.git", "ssh"),
        ("/srv/kb.git", "local"),
        ("file:///srv/kb.git", "local"),
        ("", "unknown"),
    ],
)
def test_url_protocol(url: str, expected: str):
    assert url_protocol(url) == expected


# --------------------------------------------------------------------------
# explain_failure
# --------------------------------------------------------------------------


def test_explain_names_the_action_and_the_cause():
    lines = explain_failure("push kb main", _result(AUTH_HTTPS))
    assert lines[0].startswith("Could not push kb main")
    assert "authentication" in lines[0]


def test_explain_includes_every_line_of_git_stderr():
    lines = explain_failure("push kb main", _result(AUTH_SSH))
    body = "\n".join(lines)
    for original in AUTH_SSH.strip().splitlines():
        assert original in body


def test_explain_of_an_unknown_failure_does_not_guess():
    lines = explain_failure("merge origin/main", _result(DNS))
    body = "\n".join(lines)
    assert "Could not resolve host: github.com" in body
    assert "conflict" not in body.lower()
    assert "authentication" not in body.lower()


def test_explain_reports_the_exit_code_when_git_said_nothing():
    lines = explain_failure("merge origin/main", _result("", returncode=128))
    body = "\n".join(lines)
    assert "128" in body


def test_explain_includes_caller_detail_lines():
    lines = explain_failure(
        "push kb main", _result(AUTH_HTTPS),
        detail=["remote: https://github.com/o/r.git (https)"],
    )
    assert any("remote: https://github.com/o/r.git (https)" in ln for ln in lines)


def test_explain_accepts_a_git_error():
    lines = explain_failure("clone the kb", _error(DNS))
    assert "Could not resolve host: github.com" in "\n".join(lines)


def test_explain_non_fast_forward_says_the_remote_is_ahead():
    """Domain-free: the seam knows git, not the kb. 'Resolve conflicts in kb/'
    is a caller detail line, not something git.py invents."""
    lines = explain_failure("push kb main", _result(NON_FF))
    assert "commits this push does not contain" in lines[0]
    assert "kb/" not in lines[0]


def test_explain_protected_says_protected():
    lines = explain_failure("push kb main", _result(PROTECTED))
    assert "protected" in lines[0].lower()


# --------------------------------------------------------------------------
# report_failure
# --------------------------------------------------------------------------


def test_report_prints_on_the_error_channel_and_returns_the_kind(capsys):
    kind = report_failure("push kb main", _result(AUTH_HTTPS))
    out, err = capsys.readouterr()
    assert kind == "auth"
    assert out.startswith("error: Could not push kb main")
    assert err == ""


def test_report_can_warn_instead_of_erroring(capsys):
    """Best-effort operations report the same text on the warning channel."""
    kind = report_failure("push the kb", _result(DNS), warn=True)
    out = capsys.readouterr().out
    assert kind == "unknown"
    assert "error:" not in out
    assert "Could not push the kb" in out
    assert "Could not resolve host" in out
