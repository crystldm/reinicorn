"""Tests for asset resolution (bundled _data/ and repo-root fallback)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from reinicorn.assets import _DATA_DIR, get_asset_path
from reinicorn.git import reinicorn_root


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
        "(native skills, hooks, linters) to the installed Reinicorn version |"
    ]
    assert "AGENTS" not in update_rows[0]


def test_using_reinicorn_defers_to_wiring_doc():
    """using-reinicorn routes doc authoring through the generated wiring
    doc and states the no-adapter fallback, instead of hardcoding doc
    types or skill names."""
    skill = get_asset_path(".agents/skills/using-reinicorn/SKILL.md")
    assert skill is not None
    text = skill.read_text()

    assert "references/skillset-wiring.md" in text
    assert "the creation command alone is the contract" in text


def test_native_skill_set_is_exactly_two_tracked_dirs():
    """After the superpowers-fork cutover, `.agents/skills/` tracks only the
    two Reinicorn-native skills; the 13 forked skills, `update-superpowers/`,
    and `ATTRIBUTION.md` are gone from git — they live in the superpowers
    adapter (`adapters/superpowers/`) or an adapter install instead.

    This checks `git ls-files`, not directory contents: an adapter install
    (`rcorn skills install superpowers`) populates `.agents/skills/` with
    gitignored files on disk, so a filesystem-iteration check would wrongly
    fail once this repo dogfoods its own adapter.
    """
    root = reinicorn_root()
    assert root is not None
    result = subprocess.run(
        ["git", "ls-files", ".agents/skills"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    prefix = ".agents/skills/"
    tracked = [
        line[len(prefix):] for line in result.stdout.splitlines()
        if line.startswith(prefix)
    ]
    top_level_dirs = sorted({line.split("/", 1)[0] for line in tracked})
    assert top_level_dirs == ["populate-agents-md", "using-reinicorn"]


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

    assert (
        "x-access-token:${{ secrets.KB_CLEANUP_TOKEN || github.token }}" in text
    )


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


_CHECKS_WORKFLOW = "workflows/reinicorn-doc-review-checks.yml"


def _checks_workflow_text() -> str:
    path = get_asset_path(_CHECKS_WORKFLOW)
    assert path is not None and path.is_file()
    return path.read_text()


def test_doc_review_checks_workflow_structure():
    """Runs on every pull request with one job per required check: "Doc lint"
    runs the stock `rcorn kb lint` with the PR head checked out into `kb/`
    inside the Reinicorn checkout; "Candidate integrity" runs
    `rcorn _review-check` against the PR head at the checkout root."""
    text = _checks_workflow_text()
    try:
        import yaml
    except ImportError:
        assert "pull_request:" in text
        assert "name: Doc lint" in text
        assert "name: Candidate integrity" in text
        assert "rcorn kb lint" in text
        assert 'rcorn _review-check "$HEAD_REF"' in text
        return

    data = yaml.safe_load(text)
    assert "pull_request" in data[True]  # 'on:' parses as bool key True (YAML 1.1)
    jobs = data["jobs"]
    assert {j["name"] for j in jobs.values()} == {"Doc lint", "Candidate integrity"}

    lint = jobs["doc-lint"]
    assert any(s.get("run") == "rcorn kb lint" for s in lint["steps"])
    kb_checkout = [s for s in lint["steps"] if s.get("with", {}).get("path") == "kb"]
    assert len(kb_checkout) == 1
    assert kb_checkout[0]["with"]["ref"] == "${{ github.event.pull_request.head.sha }}"

    integrity = jobs["candidate-integrity"]
    check = [s for s in integrity["steps"] if "rcorn _review-check" in str(s.get("run"))]
    assert len(check) == 1
    assert check[0]["env"] == {"HEAD_REF": "${{ github.event.pull_request.head.ref }}"}
    # The integrity check diffs the PR head against main's merge-base — a
    # shallow checkout has no merge-base to diff against.
    head_checkout = [s for s in integrity["steps"] if "path" not in s.get("with", {})
                     and "repository" not in s.get("with", {})
                     and str(s.get("uses", "")).startswith("actions/checkout")]
    assert len(head_checkout) == 1
    assert head_checkout[0]["with"]["fetch-depth"] == 0


def test_doc_review_checks_workflow_hardening():
    """Same two CI hazards as the cleanup workflow, plus read-only scope:
    head.ref reaches the shell only via env indirection; code is checked out
    by head.sha (immutable) rather than head.ref; the token needs nothing
    beyond contents:read — these checks never push."""
    text = _checks_workflow_text()

    assert "HEAD_REF: ${{ github.event.pull_request.head.ref }}" in text
    assert 'rcorn _review-check "$HEAD_REF"' in text
    for line in text.splitlines():
        if "${{ github.event.pull_request.head.ref }}" in line:
            assert "run" not in line.split(":")[0], f"head.ref inlined in shell: {line}"
    assert "ref: ${{ github.event.pull_request.head.sha }}" in text
    assert "contents: read" in text
    assert "contents: write" not in text
    assert "KB_CLEANUP_TOKEN" not in text


def test_doc_review_checks_workflow_private_reinicorn_install():
    """Same install contract as the cleanup workflow: a checkout of the
    placeholder Reinicorn repo with the documented token fallback, never
    `pip install git+...`, and no legacy CLI name."""
    text = _checks_workflow_text()

    code_lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("git+" in ln for ln in code_lines)
    assert "repository: __REINICORN_REPO__" in text
    assert "token: ${{ secrets.REINICORN_INSTALL_TOKEN || github.token }}" in text
    assert "reins" not in "\n".join(code_lines).lower()
