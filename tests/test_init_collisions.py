"""Tests for skill collision detection and SSH URL conversion in init."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from reinicorn.git import https_to_ssh, remote_uses_ssh, run_git


def test_https_to_ssh_converts_github():
    assert (
        https_to_ssh("https://github.com/owner/repo")
        == "git@github.com:owner/repo.git"
    )


def test_https_to_ssh_handles_dot_git_suffix():
    assert (
        https_to_ssh("https://github.com/owner/repo.git")
        == "git@github.com:owner/repo.git"
    )


def test_https_to_ssh_passthrough_non_https():
    url = "git@github.com:owner/repo.git"
    assert https_to_ssh(url) == url


def test_remote_uses_ssh_true(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git("init", "-q", cwd=repo)
    run_git(
        "remote", "add", "origin", "git@github.com:test/test.git",
        cwd=repo,
    )
    assert remote_uses_ssh(cwd=repo) is True


def test_remote_uses_ssh_false(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git("init", "-q", cwd=repo)
    run_git(
        "remote", "add", "origin", "https://github.com/test/test.git",
        cwd=repo,
    )
    assert remote_uses_ssh(cwd=repo) is False


def test_create_github_remote_converts_to_ssh():
    """When parent repo uses SSH, _create_github_remote should return SSH URL."""
    from reinicorn.commands.init import _create_github_remote

    with patch("reinicorn.commands.init.gh_repo_create",
               return_value="https://github.com/owner/my-kb"), \
         patch("reinicorn.commands.init.remote_uses_ssh", return_value=True):
        url = _create_github_remote("my-project", name="my-kb")

    assert url == "git@github.com:owner/my-kb.git"


def test_create_github_remote_keeps_https_when_parent_uses_https():
    """When parent repo uses HTTPS, keep the HTTPS URL."""
    from reinicorn.commands.init import _create_github_remote

    with patch("reinicorn.commands.init.gh_repo_create",
               return_value="https://github.com/owner/my-kb"), \
         patch("reinicorn.commands.init.remote_uses_ssh", return_value=False):
        url = _create_github_remote("my-project", name="my-kb")

    assert url == "https://github.com/owner/my-kb"


def test_check_skill_collisions_warns_on_user_level(tmp_path: Path, capsys):
    """Should warn when user-level skills overlap with reins skills."""
    from reinicorn.commands.init import _check_skill_collisions

    user_skills = tmp_path / ".claude" / "skills"
    user_skills.mkdir(parents=True)
    (user_skills / "brainstorming").mkdir()
    (user_skills / "my-custom-skill").mkdir()

    with patch("pathlib.Path.home", return_value=tmp_path):
        _check_skill_collisions(["brainstorming", "writing-plans", "test-driven-development"])

    out = capsys.readouterr().out
    assert "brainstorming" in out
    assert "writing-plans" not in out  # no collision


def test_check_skill_collisions_warns_on_superpowers(tmp_path: Path, capsys):
    """Should warn when superpowers plugin is enabled."""
    from reinicorn.commands.init import _check_skill_collisions

    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({
        "enabledPlugins": {"superpowers@claude-plugins-official": True}
    }))

    with patch("pathlib.Path.home", return_value=tmp_path):
        _check_skill_collisions(["brainstorming"])

    out = capsys.readouterr().out
    assert "superpowers" in out.lower()
    assert "disabledPlugins" in out


def test_check_skill_collisions_silent_when_no_conflicts(tmp_path: Path, capsys):
    """Should not warn when there are no collisions."""
    from reinicorn.commands.init import _check_skill_collisions

    # Empty user skills dir
    user_skills = tmp_path / ".claude" / "skills"
    user_skills.mkdir(parents=True)

    # No superpowers in settings
    settings = tmp_path / ".claude" / "settings.json"
    settings.write_text(json.dumps({"enabledPlugins": {}}))

    with patch("pathlib.Path.home", return_value=tmp_path):
        _check_skill_collisions(["brainstorming"])

    out = capsys.readouterr().out
    assert "collision" not in out.lower()
    assert "superpowers" not in out.lower()
