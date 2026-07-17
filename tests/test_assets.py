"""Tests for asset resolution (bundled _data/ and repo-root fallback)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from reinicorn.assets import _DATA_DIR, get_asset_path


def test_bundled_assets_found_when_data_dir_exists(tmp_path: Path):
    """get_asset_path returns bundled path when _data/ contains the asset."""
    data = tmp_path / "_data"
    template = data / "templates" / "AGENTS.md"
    template.parent.mkdir(parents=True)
    template.write_text("# Agents\n")

    with patch("reinicorn.assets._DATA_DIR", data):
        result = get_asset_path("templates/AGENTS.md")
    assert result is not None
    assert result == template


def test_falls_back_to_repo_root(tmp_path: Path):
    """get_asset_path falls back to repo root when _data/ missing."""
    empty_data = tmp_path / "_data"
    empty_data.mkdir()

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "hooks").mkdir()
    (repo_root / "hooks" / "pre-push").write_text("#!/bin/bash\n")

    with patch("reinicorn.assets._DATA_DIR", empty_data), \
         patch("reinicorn.git.reinicorn_root", return_value=repo_root):
        result = get_asset_path("hooks")
    assert result is not None
    assert result == repo_root / "hooks"


def test_returns_none_when_not_found(tmp_path: Path):
    """get_asset_path returns None when asset is missing everywhere."""
    empty_data = tmp_path / "_data"
    empty_data.mkdir()

    with patch("reinicorn.assets._DATA_DIR", empty_data), \
         patch("reinicorn.git.reinicorn_root", return_value=tmp_path):
        result = get_asset_path("nonexistent")
    assert result is None


def test_data_dir_points_to_package():
    """_DATA_DIR should be inside the Reinicorn package directory."""
    assert _DATA_DIR.parent.name == "reinicorn"


def test_using_reinicorn_update_guidance_excludes_agents() -> None:
    """The shipped workflow guide lists only update-managed asset groups."""
    skill = get_asset_path(".agents/skills/using-reinicorn/SKILL.md")
    assert skill is not None
    update_rows = [
        line for line in skill.read_text().splitlines()
        if line.startswith("| `rcorn update")
    ]

    assert update_rows == [
        "| `rcorn update [--diff X]` | Re-sync bundled files "
        "(skills, hooks, linters) to the installed Reinicorn version |"
    ]
    assert "AGENTS" not in update_rows[0]


def test_doc_review_cleanup_workflow_asset_resolves():
    """The Reinicorn review setup workflow template is bundled/discoverable."""
    result = get_asset_path("workflows/reinicorn-doc-review-cleanup.yml")
    assert result is not None
    assert result.is_file()


def test_doc_review_cleanup_workflow_structure():
    """Structural sanity check on the workflow trigger + cleanup invocation.

    Parses with PyYAML if available in the venv; otherwise falls back to
    text assertions on the key trigger/job fields (pyyaml is not a project
    dependency, so we don't require it).
    """
    path = get_asset_path("workflows/reinicorn-doc-review-cleanup.yml")
    assert path is not None
    text = path.read_text()
    try:
        import yaml
    except ImportError:
        assert "pull_request" in text
        assert "types: [closed]" in text
        assert (
            "startsWith(github.event.pull_request.head.ref, 'review/')" in text
        )
        assert "rcorn _review-cleanup" in text
        return

    data = yaml.safe_load(text)
    assert "pull_request" in data[True]  # 'on:' is parsed as bool key True by YAML 1.1
    assert data[True]["pull_request"]["types"] == ["closed"]
    job = data["jobs"]["cleanup"]
    assert "review/" in job["if"]
    steps_text = " ".join(str(step.get("run", "")) for step in job["steps"])
    assert "rcorn _review-cleanup" in steps_text


def test_doc_review_cleanup_workflow_hardening():
    """Two CI hazards, pinned:

    1. `head.ref` is attacker-controlled (GitHub docs list it as untrusted
       for script injection) — it must reach the shell only via env
       indirection, never interpolated into a run: script.
    2. actions/checkout persists its token in the checkout's LOCAL git
       config, which the fresh temp clone inside _review-cleanup does not
       inherit — origin must carry an authenticated URL for the clone/push.
    """
    path = get_asset_path("workflows/reinicorn-doc-review-cleanup.yml")
    assert path is not None
    text = path.read_text()

    assert "HEAD_REF: ${{ github.event.pull_request.head.ref }}" in text
    assert 'rcorn _review-cleanup "$HEAD_REF"' in text
    # No shell line may interpolate head.ref directly (the if: expression
    # context is safe and exempt).
    for line in text.splitlines():
        if "${{ github.event.pull_request.head.ref }}" in line:
            assert "run" not in line.split(":")[0], f"head.ref inlined in shell: {line}"

    assert "x-access-token:${{ github.token }}" in text


def test_doc_review_cleanup_workflow_private_reinicorn_install():
    """Installing Reinicorn must work while the Reinicorn repo is private, and must
    not require the kb submodule:

    - `pip install git+...` is forbidden — pip unconditionally runs
      `git submodule update --init --recursive`, which fails on the kb
      submodule's SSH URL (no keys on a runner) and on private kb repos.
    - Instead, actions/checkout fetches the Reinicorn repo (submodules stay
      untouched by default) using the optional REINICORN_INSTALL_TOKEN kb-repo
      secret (fine-grained PAT, Contents:read on the Reinicorn repo), falling
      back to the runner token — which suffices once Reinicorn is public.
    """
    path = get_asset_path("workflows/reinicorn-doc-review-cleanup.yml")
    assert path is not None
    text = path.read_text()

    code_lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("git+" in ln for ln in code_lines)
    # The install source is a placeholder `review setup` fills from the
    # installed package's Repository URL — no owner/repo hardcoded here.
    assert "repository: __REINICORN_REPO__" in text
    assert "token: ${{ secrets.REINICORN_INSTALL_TOKEN || github.token }}" in text
    assert "pip install ./.reinicorn-src" in text
    assert "rcorn _review-cleanup" in text
    assert "reins" not in "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    ).lower()
