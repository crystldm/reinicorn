"""Tests for reinicorn.github — gh CLI wrapper."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from reinicorn.github import (
    PR_STATE_OPEN,
    REVIEW_DECISION_APPROVED,
    gh_auth_login,
    gh_authenticated,
    gh_available,
    gh_login,
    gh_pr_close,
    gh_pr_create,
    gh_pr_merge,
    gh_pr_view,
    gh_repo_create,
    gh_repo_is_solo,
    run_gh,
)


def test_gh_available_true():
    with patch("shutil.which", return_value="/usr/bin/gh"):
        assert gh_available() is True


def test_gh_available_false():
    with patch("shutil.which", return_value=None):
        assert gh_available() is False


def test_gh_authenticated_true():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.returncode = 0
        assert gh_authenticated() is True
        mock.assert_called_once_with("auth", "status", check=False)


def test_gh_authenticated_false():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.returncode = 1
        assert gh_authenticated() is False


def test_run_gh_check_true_raises_on_failure():
    with patch("subprocess.run") as mock:
        mock.return_value.returncode = 1
        mock.return_value.stderr = "not logged in"
        with pytest.raises(RuntimeError, match="gh failed"):
            run_gh("auth", "status", check=True)


def test_run_gh_raises_when_gh_not_installed():
    with (
        patch("subprocess.run", side_effect=FileNotFoundError("gh")),
        pytest.raises(RuntimeError, match="gh CLI not found"),
    ):
        run_gh("auth", "status")


def test_run_gh_check_false_returns_result():
    with patch("subprocess.run") as mock:
        mock.return_value.returncode = 1
        mock.return_value.stderr = "not logged in"
        r = run_gh("auth", "status", check=False)
        assert r.returncode == 1


def test_gh_auth_login_success():
    with patch("subprocess.run") as mock:
        mock.return_value.returncode = 0
        assert gh_auth_login() is True
        mock.assert_called_once_with(["gh", "auth", "login"], check=False, text=True)


def test_gh_auth_login_failure():
    with patch("subprocess.run") as mock:
        mock.return_value.returncode = 1
        assert gh_auth_login() is False


def test_gh_repo_create_returns_url():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.stdout = "https://github.com/user/my-kb\n"
        mock.return_value.returncode = 0
        url = gh_repo_create("my-kb")
        assert url == "https://github.com/user/my-kb"
        call_args = mock.call_args[0]
        assert "repo" in call_args
        assert "create" in call_args
        assert "my-kb" in call_args
        assert "--private" in call_args


def test_gh_repo_create_with_description():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.stdout = "https://github.com/user/my-kb\n"
        mock.return_value.returncode = 0
        gh_repo_create("my-kb", description="Kb for my-project")
        call_args = mock.call_args[0]
        assert "--description" in call_args


def test_constants():
    assert PR_STATE_OPEN == "OPEN"
    assert REVIEW_DECISION_APPROVED == "APPROVED"


def test_gh_pr_create_returns_url_and_invokes_expected_argv():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.stdout = "https://github.com/o/r/pull/7\n"
        mock.return_value.returncode = 0
        url = gh_pr_create(
            "o/r",
            head="review/myrepo/spec-x",
            title="t",
            body="b",
            reviewers=["alice", "bob"],
        )
        assert url == "https://github.com/o/r/pull/7"
        call_args = mock.call_args[0]
        assert list(call_args[:9]) == [
            "pr", "create", "--repo", "o/r", "--head", "review/myrepo/spec-x",
            "--title", "t", "--body",
        ]
        assert call_args[9] == "b"
        assert call_args.count("--reviewer") == 2
        idx = call_args.index("--reviewer")
        assert call_args[idx + 1] == "alice"
        idx2 = call_args.index("--reviewer", idx + 1)
        assert call_args[idx2 + 1] == "bob"


def test_gh_pr_create_no_reviewers_none():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.stdout = "https://github.com/o/r/pull/7\n"
        mock.return_value.returncode = 0
        gh_pr_create("o/r", head="h", title="t", body="b", reviewers=None)
        call_args = mock.call_args[0]
        assert "--reviewer" not in call_args


def test_gh_pr_create_no_reviewers_empty_list():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.stdout = "https://github.com/o/r/pull/7\n"
        mock.return_value.returncode = 0
        gh_pr_create("o/r", head="h", title="t", body="b", reviewers=[])
        call_args = mock.call_args[0]
        assert "--reviewer" not in call_args


def test_gh_pr_view_parses_json_stdout():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.returncode = 0
        mock.return_value.stdout = (
            '{"number": 7, "state": "OPEN", "reviewDecision": "APPROVED", '
            '"url": "https://github.com/o/r/pull/7", "latestReviews": []}'
        )
        pr = gh_pr_view("o/r", head="review/myrepo/spec-x")
        assert pr is not None
        assert pr["number"] == 7
        assert pr["reviewDecision"] == "APPROVED"
        call_args = mock.call_args[0]
        assert list(call_args) == [
            "pr", "view", "review/myrepo/spec-x", "--repo", "o/r",
            "--json", "number,state,reviewDecision,url,latestReviews",
        ]
        assert mock.call_args.kwargs.get("check") is False


def test_gh_pr_view_returns_none_on_nonzero_exit():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.returncode = 1
        mock.return_value.stdout = ""
        assert gh_pr_view("o/r", head="h") is None


def test_gh_pr_view_returns_none_on_empty_stdout():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.returncode = 0
        mock.return_value.stdout = "   "
        assert gh_pr_view("o/r", head="h") is None


def test_gh_pr_merge_invokes_expected_argv():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.returncode = 0
        gh_pr_merge("o/r", 7)
        assert mock.call_args[0] == ("pr", "merge", "7", "--repo", "o/r", "--squash")


def test_gh_pr_merge_failure_raises_with_tailored_hint():
    with patch("subprocess.run") as mock:
        mock.return_value.returncode = 1
        mock.return_value.stderr = "Pull request #7 is not mergeable"
        with pytest.raises(RuntimeError) as exc_info:
            gh_pr_merge("o/r", 7)
        message = str(exc_info.value)
        assert "The PR may be unmergeable" in message
        assert "gh auth status" not in message


def test_gh_pr_close_with_comment():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.returncode = 0
        gh_pr_close("o/r", 7, comment="bye")
        assert mock.call_args[0] == (
            "pr", "close", "7", "--repo", "o/r", "--comment", "bye"
        )


def test_gh_pr_close_without_comment():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.returncode = 0
        gh_pr_close("o/r", 7)
        assert mock.call_args[0] == ("pr", "close", "7", "--repo", "o/r")


def test_run_gh_input_text_passed_to_subprocess_run():
    with patch("subprocess.run") as mock:
        mock.return_value.returncode = 0
        mock.return_value.stdout = ""
        run_gh("api", "--input", "-", input_text="{}")
        kwargs = mock.call_args.kwargs
        assert kwargs.get("input") == "{}"
        assert kwargs.get("text") is True


# ── gh_repo_is_solo / gh_login ───────────────────────────────


def _solo_mock(mock, *, returncode=0, stdout="[]"):
    mock.return_value.returncode = returncode
    mock.return_value.stdout = stdout


def test_repo_is_solo_true_for_single_push_collaborator():
    with patch("reinicorn.github.run_gh") as mock:
        _solo_mock(mock, stdout='[{"login": "owner", "permissions": {"push": true}}]')
        assert gh_repo_is_solo("o/r") is True


def test_repo_is_solo_false_for_two_push_collaborators():
    with patch("reinicorn.github.run_gh") as mock:
        _solo_mock(mock, stdout=(
            '[{"login": "owner", "permissions": {"push": true}}, '
            '{"login": "alice", "permissions": {"push": true}}]'
        ))
        assert gh_repo_is_solo("o/r") is False


def test_repo_is_solo_ignores_read_only_collaborators():
    """A second collaborator with only pull access does not make it non-solo."""
    with patch("reinicorn.github.run_gh") as mock:
        _solo_mock(mock, stdout=(
            '[{"login": "owner", "permissions": {"push": true}}, '
            '{"login": "bob", "permissions": {"push": false, "pull": true}}]'
        ))
        assert gh_repo_is_solo("o/r") is True


def test_repo_is_solo_none_on_listing_failure():
    with patch("reinicorn.github.run_gh") as mock:
        _solo_mock(mock, returncode=1, stdout="")
        assert gh_repo_is_solo("o/r") is None


def test_repo_is_solo_none_on_unparseable_json():
    with patch("reinicorn.github.run_gh") as mock:
        _solo_mock(mock, stdout="not json")
        assert gh_repo_is_solo("o/r") is None


def test_repo_is_solo_paginates_collaborators():
    with patch("reinicorn.github.run_gh") as mock:
        _solo_mock(mock, stdout='[{"login": "owner", "permissions": {"push": true}}]')
        gh_repo_is_solo("o/r")
        argv = mock.call_args[0]
        assert argv[0] == "api"
        assert "repos/o/r/collaborators" in argv[1]
        assert "--paginate" in argv


def test_gh_login_returns_login():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.returncode = 0
        mock.return_value.stdout = "octocat\n"
        assert gh_login() == "octocat"


def test_gh_login_none_on_failure():
    with patch("reinicorn.github.run_gh") as mock:
        mock.return_value.returncode = 1
        mock.return_value.stdout = ""
        assert gh_login() is None


# --- gh_pr_heads (gh CLI contract: `gh pr list --state X --json headRefName`) --


def _completed(rc: int, stdout: str):
    from subprocess import CompletedProcess
    return CompletedProcess(args=["gh"], returncode=rc, stdout=stdout, stderr="")


def test_gh_pr_heads_returns_head_names():
    from reinicorn.github import PR_LIST_STATE_MERGED, gh_pr_heads

    payload = '[{"headRefName": "feat/a"}, {"headRefName": "fix/b"}, {"other": 1}]'
    with patch("reinicorn.github.run_gh", return_value=_completed(0, payload)) as mock:
        assert gh_pr_heads("o/r", state=PR_LIST_STATE_MERGED) == {"feat/a", "fix/b"}
    args = mock.call_args[0]
    assert args[:6] == ("pr", "list", "--repo", "o/r", "--state", "merged")
    assert "--json" in args and "headRefName" in args


@pytest.mark.parametrize(
    "result",
    [_completed(1, ""), _completed(0, ""), _completed(0, "not json"), _completed(0, "{}")],
    ids=["failed", "empty", "garbage", "not-a-list"],
)
def test_gh_pr_heads_is_none_when_gh_cannot_answer(result):
    from reinicorn.github import PR_LIST_STATE_ALL, gh_pr_heads

    with patch("reinicorn.github.run_gh", return_value=result):
        assert gh_pr_heads("o/r", state=PR_LIST_STATE_ALL) is None


def test_gh_pr_heads_is_none_without_gh():
    from reinicorn.github import PR_LIST_STATE_ALL, gh_pr_heads

    with patch("reinicorn.github.run_gh", side_effect=RuntimeError("gh CLI not found")):
        assert gh_pr_heads("o/r", state=PR_LIST_STATE_ALL) is None
