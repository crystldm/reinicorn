"""Tests for rcorn _post-checkout — submodule init + new-branch suggestion."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from reinicorn.commands.internal.post_checkout import cmd_post_checkout
from reinicorn.git import run_git


def test_file_checkout_is_noop(submodule_repo: Path, monkeypatch, capsys):
    """checkout_type '0' (file checkout) → exit 0, no output."""
    monkeypatch.chdir(submodule_repo)
    assert cmd_post_checkout(["a", "b", "0"]) == 0
    assert capsys.readouterr().out == ""


def test_disabled_mode_is_noop(submodule_repo: Path, monkeypatch, capsys):
    """Disabled mode → no suggestion printed."""
    state_dir = submodule_repo / ".reinicorn"
    state_dir.mkdir()
    (state_dir / "mode").write_text("disabled")
    monkeypatch.chdir(submodule_repo)
    assert cmd_post_checkout(["a", "b", "1"]) == 0
    assert capsys.readouterr().out == ""


def test_new_branch_suggests_plan_create(submodule_repo: Path, monkeypatch, capsys):
    """New branch without upstream → suggests 'rcorn plan create'."""
    run_git("checkout", "-q", "-b", "feature-new-thing", cwd=submodule_repo)
    monkeypatch.chdir(submodule_repo)
    assert cmd_post_checkout(["a", "b", "1"]) == 0
    out = capsys.readouterr().out
    assert "feature-new-thing" in out
    assert "rcorn plan create" in out
    assert "/create-exec-plan" not in out


def test_ticket_id_detected_in_branch(submodule_repo: Path, monkeypatch, capsys):
    """Branch containing a JIRA-style ticket id → id shown in suggestion."""
    run_git("checkout", "-q", "-b", "feature/ABC-123-do-thing", cwd=submodule_repo)
    monkeypatch.chdir(submodule_repo)
    assert cmd_post_checkout(["a", "b", "1"]) == 0
    out = capsys.readouterr().out
    assert "ABC-123" in out
    assert "rcorn plan create" in out


def test_init_kb_refuses_malicious_remote_url(tmp_path: Path, monkeypatch, capsys):
    """A malicious REINICORN_KB_REMOTE recorded in .reinicorn-config (an
    ``ext::`` transport helper, repository-controlled) must never reach
    `git clone` from the post-checkout hook — validate_git_url runs before
    any clone, same as every other kb clone path (setup_kb_clone,
    apply_kb_remote_url). Regression test for C1.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git("init", "-q", "-b", "main", str(repo))
    run_git("config", "user.email", "test@test.com", cwd=repo)
    run_git("config", "user.name", "Test User", cwd=repo)
    (repo / ".gitignore").write_text("kb/\n")
    (repo / ".reinicorn-config").write_text(
        "REINICORN_KB_REMOTE=\"ext::sh -c 'touch /tmp/reinicorn-pwned'\"\n"
    )
    run_git("add", "-A", cwd=repo)
    run_git("commit", "-q", "-m", "init", cwd=repo)

    monkeypatch.chdir(repo)
    # Mock run_git so that if the fix regressed and a clone were attempted,
    # it would not actually execute the payload — the assertion below on
    # the mock's call args is what proves the clone was never attempted.
    mock_run_git = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    with patch(
        "reinicorn.commands.internal.post_checkout.run_git", mock_run_git,
    ):
        assert cmd_post_checkout(["a", "b", "1"]) == 0

    clone_calls = [c for c in mock_run_git.call_args_list if "clone" in c.args]
    assert clone_calls == []
    assert not (repo / "kb").exists()
    out = capsys.readouterr().out
    assert "Refusing" in out
    assert "ext::" in out


# --- Restore adapter files on a fresh checkout --------------------------------


def _lock_demo_adapter_in(repo: Path, tmp_path: Path) -> Path:
    from reinicorn.skillset import installer
    from reinicorn.skillset.adapter import load_adapter

    adapter_dir = repo / "demo"
    adapter_dir.mkdir()
    (adapter_dir / "adapter.yaml").write_text(
        "name: demo\n"
        "source:\n"
        "  repo: acme/skills\n"
        "  commit: 0123456789abcdef0123456789abcdef01234567\n"
        "  annotation: v1.0.0\n"
        "skills:\n"
        "  skills/alpha: alpha\n"
        "wiring:\n"
        "  spec: [alpha]\n"
    )
    installer.install_adapter(load_adapter(adapter_dir), repo, cache_dir=tmp_path / "cache")
    return repo / ".agents" / "skills" / "alpha" / "scratch.md"


def test_post_checkout_restores_missing_adapter_files(
    kb_clone_repo: Path, tmp_path: Path, fake_skillset_fetch, monkeypatch
) -> None:
    """A new clone or worktree has the committed lock and no skill files."""

    scratch = _lock_demo_adapter_in(kb_clone_repo, tmp_path)
    scratch.unlink()
    monkeypatch.chdir(kb_clone_repo)

    with patch(
        "reinicorn.commands.internal.post_checkout.hook_check", return_value=True,
    ):
        assert cmd_post_checkout(["", "", "1"]) == 0

    assert scratch.is_file()


def test_post_checkout_restore_failure_never_fails_the_checkout(
    kb_clone_repo: Path, tmp_path: Path, fake_skillset_fetch, monkeypatch, capsys
) -> None:
    from reinicorn.skillset import restore

    scratch = _lock_demo_adapter_in(kb_clone_repo, tmp_path)
    scratch.unlink()
    monkeypatch.chdir(kb_clone_repo)

    def boom(*_a, **_k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(restore, "fetch_source", boom)
    with patch(
        "reinicorn.commands.internal.post_checkout.hook_check", return_value=True,
    ):
        assert cmd_post_checkout(["", "", "1"]) == 0

    assert not scratch.exists()
    assert "unexpected" in capsys.readouterr().out
