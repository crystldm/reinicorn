"""Tests for kb remote URL resolution.

Idea: kb/reinicorn/ideas/michael-biehl/
      worktree-kb-init-uses-the-gitmodules-https-url-and-drops-the.md

A kb clone created by the post-checkout hook must inherit the remote the user
actually uses, not the URL recorded in repository-controlled config.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from reinicorn.git import remote_url, run_git
from reinicorn.kb_remote import (
    adapt_url_to_git_protocol,
    apply_kb_remote_url,
    configured_kb_remote_url,
    git_protocol_preference,
    inherited_kb_remote_url,
    resolve_kb_remote_url,
)

HTTPS = "https://github.com/crystldm/reinicorn-kb.git"
SSH = "git@github.com:crystldm/reinicorn-kb.git"


def _gh(stdout: str, returncode: int = 0):
    """A patch target returning a canned `gh` CompletedProcess."""
    return subprocess.CompletedProcess(["gh"], returncode, stdout, "")


def _add_worktree(parent: Path, name: str) -> Path:
    wt = parent.parent / name
    run_git("worktree", "add", "-q", str(wt), "-b", name, cwd=parent)
    return wt


# --------------------------------------------------------------------------
# git_protocol_preference
# --------------------------------------------------------------------------


def test_git_protocol_preference_queries_the_host_scope():
    """The global `gh config get git_protocol` is not authoritative.

    gh stores a per-host git_protocol in hosts.yml that overrides the global
    default in config.yml; a machine can read 'https' globally while every
    github.com operation uses ssh. Only the host-scoped read is correct.
    """
    with patch("reinicorn.kb_remote.run_gh", return_value=_gh("ssh\n")) as mock_gh:
        assert git_protocol_preference() == "ssh"
    args = mock_gh.call_args.args
    assert "-h" in args and "github.com" in args
    assert "git_protocol" in args


def test_git_protocol_preference_empty_when_gh_fails():
    with patch("reinicorn.kb_remote.run_gh", return_value=_gh("", returncode=1)):
        assert git_protocol_preference() == ""


def test_git_protocol_preference_empty_when_gh_missing():
    with patch("reinicorn.kb_remote.run_gh", side_effect=RuntimeError("no gh")):
        assert git_protocol_preference() == ""


# --------------------------------------------------------------------------
# adapt_url_to_git_protocol
# --------------------------------------------------------------------------


def test_adapt_rewrites_https_to_ssh_when_gh_says_ssh():
    with patch("reinicorn.kb_remote.git_protocol_preference", return_value="ssh"):
        assert adapt_url_to_git_protocol(HTTPS) == SSH


def test_adapt_leaves_https_alone_when_gh_says_https():
    """HTTPS + a credential helper is a legitimate setup — never force ssh."""
    with patch("reinicorn.kb_remote.git_protocol_preference", return_value="https"):
        assert adapt_url_to_git_protocol(HTTPS) == HTTPS


def test_adapt_never_rewrites_ssh_to_https():
    """One-way by design: gh reports 'https' for any host it has no entry for,
    so treating that as evidence would break every ssh-only user."""
    with patch("reinicorn.kb_remote.git_protocol_preference", return_value="https"):
        assert adapt_url_to_git_protocol(SSH) == SSH


def test_adapt_leaves_non_github_urls_alone():
    with patch("reinicorn.kb_remote.git_protocol_preference", return_value="ssh"):
        assert (
            adapt_url_to_git_protocol("https://gitlab.com/o/r.git")
            == "https://gitlab.com/o/r.git"
        )


def test_adapt_leaves_local_paths_alone():
    with patch("reinicorn.kb_remote.git_protocol_preference", return_value="ssh"):
        assert adapt_url_to_git_protocol("/srv/kb.git") == "/srv/kb.git"


def test_adapt_leaves_urls_alone_when_protocol_unknown():
    with patch("reinicorn.kb_remote.git_protocol_preference", return_value=""):
        assert adapt_url_to_git_protocol(HTTPS) == HTTPS


def test_adapt_handles_https_url_without_dot_git():
    with patch("reinicorn.kb_remote.git_protocol_preference", return_value="ssh"):
        assert adapt_url_to_git_protocol("https://github.com/o/r") == "git@github.com:o/r.git"


# --------------------------------------------------------------------------
# inherited_kb_remote_url
# --------------------------------------------------------------------------


def test_inherited_url_reads_the_main_checkouts_kb(submodule_repo: Path, tmp_path: Path):
    """A worktree inherits the main checkout's kb origin, local override included."""
    alt = tmp_path / "kb-remote-override"
    run_git("-c", "protocol.file.allow=always", "clone", "--bare",
            str(tmp_path / "kb-remote"), str(alt))
    run_git("remote", "set-url", "origin", str(alt), cwd=submodule_repo / "kb")

    wt = _add_worktree(submodule_repo, "wt-inherit")
    assert inherited_kb_remote_url(wt) == str(alt)


def test_inherited_url_in_the_main_checkout_itself(submodule_repo: Path):
    assert inherited_kb_remote_url(submodule_repo) == remote_url(submodule_repo / "kb")


def test_inherited_url_empty_without_a_kb_clone(tmp_path: Path):
    repo = tmp_path / "bare-project"
    repo.mkdir()
    run_git("init", "-q", "-b", "main", str(repo))
    assert inherited_kb_remote_url(repo) == ""


def test_inherited_url_empty_outside_a_git_repo(tmp_path: Path):
    """--git-common-dir fails; degrade to "nothing inherited", never crash."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert inherited_kb_remote_url(plain) == ""


def test_inherited_url_skips_a_kb_clone_with_no_origin(tmp_path: Path):
    repo = tmp_path / "no-origin"
    repo.mkdir()
    run_git("init", "-q", "-b", "main", str(repo))
    run_git("init", "-q", "-b", "main", str(repo / "kb"))
    assert inherited_kb_remote_url(repo) == ""


# --------------------------------------------------------------------------
# configured_kb_remote_url
# --------------------------------------------------------------------------


def test_configured_url_prefers_reinicorn_config(tmp_path: Path):
    repo = tmp_path / "cfg"
    repo.mkdir()
    (repo / ".reinicorn-config").write_text(f'REINICORN_KB_REMOTE="{HTTPS}"\n')
    (repo / ".gitmodules").write_text(
        '[submodule "kb"]\n\tpath = kb\n\turl = https://example.invalid/other.git\n'
    )
    assert configured_kb_remote_url(repo) == HTTPS


def test_configured_url_falls_back_to_gitmodules(tmp_path: Path):
    repo = tmp_path / "gm"
    repo.mkdir()
    (repo / ".gitmodules").write_text(
        f'[submodule "kb"]\n\tpath = kb\n\turl = {HTTPS}\n\tbranch = main\n'
    )
    assert configured_kb_remote_url(repo) == HTTPS


def test_configured_url_ignores_other_gitmodules_sections(tmp_path: Path):
    repo = tmp_path / "gm2"
    repo.mkdir()
    (repo / ".gitmodules").write_text(
        '[submodule "vendor"]\n\tpath = vendor\n\turl = https://example.invalid/v.git\n'
        f'[submodule "kb"]\n\tpath = kb\n\turl = {HTTPS}\n'
    )
    assert configured_kb_remote_url(repo) == HTTPS


def test_configured_url_empty_when_nothing_declares_it(tmp_path: Path):
    repo = tmp_path / "nothing"
    repo.mkdir()
    assert configured_kb_remote_url(repo) == ""


def test_configured_url_empty_when_gitmodules_has_no_kb_url(tmp_path: Path):
    repo = tmp_path / "gm3"
    repo.mkdir()
    (repo / ".gitmodules").write_text('[submodule "kb"]\n\tpath = kb\n\tbranch = main\n')
    assert configured_kb_remote_url(repo) == ""


# --------------------------------------------------------------------------
# resolve_kb_remote_url
# --------------------------------------------------------------------------


def test_resolve_prefers_an_existing_clone_over_config(
    submodule_repo: Path, tmp_path: Path,
):
    alt = tmp_path / "kb-remote-local"
    run_git("-c", "protocol.file.allow=always", "clone", "--bare",
            str(tmp_path / "kb-remote"), str(alt))
    run_git("remote", "set-url", "origin", str(alt), cwd=submodule_repo / "kb")
    (submodule_repo / ".reinicorn-config").write_text(
        f'REINICORN_KB_REMOTE="{HTTPS}"\n'
    )
    wt = _add_worktree(submodule_repo, "wt-resolve")
    assert resolve_kb_remote_url(wt) == str(alt)


def test_resolve_adapts_the_configured_url_to_the_git_protocol(tmp_path: Path):
    repo = tmp_path / "fresh"
    repo.mkdir()
    run_git("init", "-q", "-b", "main", str(repo))
    (repo / ".reinicorn-config").write_text(f'REINICORN_KB_REMOTE="{HTTPS}"\n')
    with patch("reinicorn.kb_remote.git_protocol_preference", return_value="ssh"):
        assert resolve_kb_remote_url(repo) == SSH


def test_resolve_empty_when_nothing_is_known(tmp_path: Path):
    repo = tmp_path / "unknown"
    repo.mkdir()
    run_git("init", "-q", "-b", "main", str(repo))
    assert resolve_kb_remote_url(repo) == ""


# --------------------------------------------------------------------------
# apply_kb_remote_url
# --------------------------------------------------------------------------


def test_apply_sets_the_origin_url(submodule_repo: Path):
    kb = submodule_repo / "kb"
    assert apply_kb_remote_url(kb, "/srv/kb-elsewhere.git") is True
    assert remote_url(kb) == "/srv/kb-elsewhere.git"


def test_apply_is_a_noop_when_already_correct(submodule_repo: Path):
    kb = submodule_repo / "kb"
    assert apply_kb_remote_url(kb, remote_url(kb)) is False


def test_apply_is_a_noop_for_an_empty_url(submodule_repo: Path):
    kb = submodule_repo / "kb"
    before = remote_url(kb)
    assert apply_kb_remote_url(kb, "") is False
    assert remote_url(kb) == before


def test_apply_refuses_an_unsafe_url(submodule_repo: Path, capsys):
    """.gitmodules is repository-controlled: never hand it to git unvalidated."""
    kb = submodule_repo / "kb"
    before = remote_url(kb)
    assert apply_kb_remote_url(kb, "ext::sh -c 'touch /tmp/pwned'") is False
    assert remote_url(kb) == before
    assert "Refusing" in capsys.readouterr().out


def test_apply_adds_origin_when_the_clone_has_none(tmp_path: Path):
    kb = tmp_path / "orphan-kb"
    kb.mkdir()
    run_git("init", "-q", "-b", "main", str(kb))
    assert apply_kb_remote_url(kb, "/srv/kb.git") is True
    assert remote_url(kb) == "/srv/kb.git"


# --------------------------------------------------------------------------
# The reported bug, end to end
# --------------------------------------------------------------------------


def test_post_checkout_worktree_kb_inherits_the_main_checkout_remote(
    submodule_repo: Path, tmp_path: Path, monkeypatch,
):
    """The reported failure: a worktree kb must not silently take the
    repository-recorded URL when the main checkout's kb overrides it."""
    from reinicorn.commands.internal.post_checkout import cmd_post_checkout

    recorded = remote_url(submodule_repo / "kb")
    override = tmp_path / "kb-remote-preferred"
    run_git("-c", "protocol.file.allow=always", "clone", "--bare",
            str(tmp_path / "kb-remote"), str(override))
    run_git("remote", "set-url", "origin", str(override), cwd=submodule_repo / "kb")

    run_git("config", "protocol.file.allow", "always", cwd=submodule_repo)
    wt = _add_worktree(submodule_repo, "wt-remote")

    monkeypatch.chdir(wt)
    with patch(
        "reinicorn.commands.internal.post_checkout.hook_check", return_value=True,
    ):
        assert cmd_post_checkout(["", "", "1"]) == 0

    assert (wt / "kb" / ".git").exists()
    assert remote_url(wt / "kb") == str(override)
    assert remote_url(wt / "kb") != recorded
