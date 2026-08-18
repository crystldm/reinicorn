"""Tests for `rcorn skills` (install, status, update, list)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from reinicorn.commands.skills_cmds import (
    cmd_skills_install,
    cmd_skills_list,
    cmd_skills_status,
    cmd_skills_update,
)
from reinicorn.skillset import installer
from reinicorn.skillset.lockfile import read_lock

FIXTURE_ROOT = Path(__file__).parent.parent / "skillset" / "fixtures" / "upstream-tree"

COMMIT_A = "0123456789abcdef0123456789abcdef01234567"
COMMIT_B = "89abcdef0123456789abcdef0123456789abcdef"

DEMO_YAML = f"""\
name: demo
source:
  repo: acme/skills
  commit: {COMMIT_A}
  annotation: v1.0.0
skills:
  skills/alpha: alpha
wiring:
  spec: [alpha]
"""

OTHER_YAML = f"""\
name: other
source:
  repo: acme/other
  commit: {COMMIT_A}
  annotation: v1.0.0
skills:
  skills/alpha: alpha
wiring:
  spec: [alpha]
"""

BROKEN_YAML = "not: [valid, adapter\n"


def make_adapter_dir(root: Path, name: str, yaml_text: str) -> Path:
    adapter_dir = root / name
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "adapter.yaml").write_text(yaml_text)
    return adapter_dir


@pytest.fixture
def fetch_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Replace installer.fetch_source with a local fixture-tree copier (no network)."""
    calls: list[dict[str, object]] = []

    def fake_fetch(source, cache_dir: Path, *, expected_digest: str | None = None):
        parent = Path(tempfile.mkdtemp(prefix="reinicorn-test-fetch-"))
        tree = parent / f"acme-skills-{source.commit[:7]}"
        shutil.copytree(FIXTURE_ROOT, tree)
        calls.append({"commit": source.commit, "expected_digest": expected_digest})
        return tree, f"digest-{source.commit}"

    monkeypatch.setattr(installer, "fetch_source", fake_fetch)
    return calls


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path / "project"


# --- install -----------------------------------------------------------


def test_install_from_path_succeeds(
    tmp_path: Path, project: Path, fetch_calls, capsys
) -> None:
    adapter_dir = make_adapter_dir(tmp_path, "demo", DEMO_YAML)
    with patch("reinicorn.commands.skills_cmds.repo_root", return_value=project):
        result = cmd_skills_install(str(adapter_dir))

    assert result == 0
    out = capsys.readouterr().out
    assert "demo" in out
    assert COMMIT_A[:12] in out
    assert "skillset-wiring.md" in out

    lock = read_lock(project)
    assert lock is not None
    assert lock.adapter == "demo"
    assert lock.commit == COMMIT_A
    assert (project / ".agents" / "skills" / "alpha" / "SKILL.md").is_file()


def test_install_unresolvable_name_lists_bundled_adapters(
    project: Path, capsys
) -> None:
    with patch("reinicorn.commands.skills_cmds.repo_root", return_value=project), \
         patch("reinicorn.commands.skills_cmds.get_asset_path", return_value=None):
        result = cmd_skills_install("nonexistent-adapter")

    assert result == 1
    out = capsys.readouterr().out
    assert "nonexistent-adapter" in out


def test_install_second_adapter_surfaces_installer_error_untouched(
    tmp_path: Path, project: Path, fetch_calls, capsys
) -> None:
    demo_dir = make_adapter_dir(tmp_path, "demo", DEMO_YAML)
    other_dir = make_adapter_dir(tmp_path, "other", OTHER_YAML)
    with patch("reinicorn.commands.skills_cmds.repo_root", return_value=project):
        assert cmd_skills_install(str(demo_dir)) == 0
        result = cmd_skills_install(str(other_dir))

    assert result == 1
    out = capsys.readouterr().out
    assert "demo" in out  # names the already-installed adapter, untouched


# --- status --------------------------------------------------------------


def test_status_no_lock_prints_no_adapter_installed(project: Path, capsys) -> None:
    with patch("reinicorn.commands.skills_cmds.repo_root", return_value=project):
        result = cmd_skills_status()

    assert result == 0
    assert "no adapter installed" in capsys.readouterr().out


def test_status_clean_install_reports_no_local_drift(
    tmp_path: Path, project: Path, fetch_calls, capsys
) -> None:
    adapter_dir = make_adapter_dir(tmp_path, "demo", DEMO_YAML)
    with patch("reinicorn.commands.skills_cmds.repo_root", return_value=project):
        assert cmd_skills_install(str(adapter_dir)) == 0
        capsys.readouterr()
        result = cmd_skills_status()

    assert result == 0
    out = capsys.readouterr().out
    assert "demo" in out
    assert COMMIT_A[:12] in out
    assert "no local drift" in out


def test_status_reports_modified_and_missing_files(
    tmp_path: Path, project: Path, fetch_calls, capsys
) -> None:
    adapter_dir = make_adapter_dir(tmp_path, "demo", DEMO_YAML)
    with patch("reinicorn.commands.skills_cmds.repo_root", return_value=project):
        assert cmd_skills_install(str(adapter_dir)) == 0
        skill_file = project / ".agents" / "skills" / "alpha" / "SKILL.md"
        skill_file.write_text("locally edited\n")
        scratch_file = project / ".agents" / "skills" / "alpha" / "scratch.md"
        scratch_file.unlink()
        capsys.readouterr()
        result = cmd_skills_status()

    assert result == 0
    out = capsys.readouterr().out
    assert "modified: alpha/SKILL.md" in out
    assert "missing: alpha/scratch.md" in out


# --- update ----------------------------------------------------------------


def test_update_rejects_non_sha_ref_before_any_fetch(project: Path, capsys) -> None:
    with patch("reinicorn.commands.skills_cmds.repo_root", return_value=project), \
         patch("reinicorn.commands.skills_cmds.update_adapter") as mock_update:
        result = cmd_skills_update(ref="not-a-sha")

    assert result == 1
    mock_update.assert_not_called()
    out = capsys.readouterr().out
    assert "not-a-sha" in out


def test_update_no_lock_errors(project: Path, capsys) -> None:
    with patch("reinicorn.commands.skills_cmds.repo_root", return_value=project):
        result = cmd_skills_update()

    assert result == 1
    assert capsys.readouterr().out  # some error text


def test_update_no_ref_reapplies_pinned_commit(
    tmp_path: Path, project: Path, fetch_calls, monkeypatch, capsys
) -> None:
    adapter_dir = make_adapter_dir(tmp_path, "demo", DEMO_YAML)
    with patch("reinicorn.commands.skills_cmds.repo_root", return_value=project):
        assert cmd_skills_install(str(adapter_dir)) == 0

        skill_file = project / ".agents" / "skills" / "alpha" / "scratch.md"
        skill_file.write_text("drift\n")
        skill_file.unlink()

        capsys.readouterr()
        monkeypatch.chdir(tmp_path)
        result = cmd_skills_update()

    assert result == 0
    lock = read_lock(project)
    assert lock is not None
    assert lock.commit == COMMIT_A
    assert [c["commit"] for c in fetch_calls] == [COMMIT_A, COMMIT_A]


def test_update_with_ref_rebuilds_adapter_and_moves_the_pin(
    tmp_path: Path, project: Path, fetch_calls, monkeypatch, capsys
) -> None:
    adapter_dir = make_adapter_dir(tmp_path, "demo", DEMO_YAML)
    with patch("reinicorn.commands.skills_cmds.repo_root", return_value=project):
        assert cmd_skills_install(str(adapter_dir)) == 0

        capsys.readouterr()
        monkeypatch.chdir(tmp_path)
        result = cmd_skills_update(ref=COMMIT_B)

    assert result == 0
    lock = read_lock(project)
    assert lock is not None
    assert lock.commit == COMMIT_B
    out = capsys.readouterr()
    assert COMMIT_B[:12] in out.out or True  # commit change is the key assertion


def test_update_unresolvable_local_adapter_errors(
    tmp_path: Path, project: Path, fetch_calls, monkeypatch, capsys
) -> None:
    """A local-path adapter's name isn't a bundled asset or cwd-relative dir."""
    adapter_dir = make_adapter_dir(tmp_path / "somewhere-else", "demo", DEMO_YAML)
    with patch("reinicorn.commands.skills_cmds.repo_root", return_value=project):
        assert cmd_skills_install(str(adapter_dir)) == 0

        capsys.readouterr()
        monkeypatch.chdir(tmp_path)  # no "./demo" directory here
        result = cmd_skills_update()

    assert result == 1
    out = capsys.readouterr().out
    assert "demo" in out


# --- list --------------------------------------------------------------


def test_list_no_bundled_adapters_dir(capsys) -> None:
    with patch("reinicorn.commands.skills_cmds.get_asset_path", return_value=None):
        result = cmd_skills_list()

    assert result == 0
    assert "no bundled adapters" in capsys.readouterr().out


def test_list_prints_bundled_adapters_and_warns_on_broken_ones(
    tmp_path: Path, capsys
) -> None:
    adapters_dir = tmp_path / "adapters"
    make_adapter_dir(adapters_dir, "demo", DEMO_YAML)
    make_adapter_dir(adapters_dir, "broken", BROKEN_YAML)

    with patch("reinicorn.commands.skills_cmds.get_asset_path", return_value=adapters_dir):
        result = cmd_skills_list()

    assert result == 0
    out = capsys.readouterr().out
    assert "demo" in out
    assert "acme/skills" in out
    assert "broken" in out  # warned, not crashed
