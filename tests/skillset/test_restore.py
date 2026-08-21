"""Tests for reinicorn.skillset.restore — bringing lock-recorded files back.

Spec: kb/reinicorn/specs/skill-base-agnostic-reinicorn-adapter-infrastructure-for-ext.md
(lockfile as the committed record; installed skill files may be gitignored).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reinicorn.manifest import sha256_file, write_manifest
from reinicorn.skillset import installer
from reinicorn.skillset.adapter import AdapterError, load_adapter
from reinicorn.skillset.lockfile import SkillsetLock, read_lock, write_lock
from reinicorn.skillset.restore import (
    RestoreOutcome,
    ensure_adapter_files,
    missing_files,
    restore_from_lock,
)
from reinicorn.skillset.wiring import wiring_doc_path

COMMIT_A = "0123456789abcdef0123456789abcdef01234567"

DEMO_YAML = f"""\
name: demo
source:
  repo: acme/skills
  commit: {COMMIT_A}
  annotation: v1.0.0
skills:
  skills/alpha: alpha
  skills/nested/beta: beta
wiring:
  spec: [alpha]
"""

ALPHA = Path("alpha/SKILL.md")
SCRATCH = Path("alpha/scratch.md")
BETA_TEMPLATE = Path("beta/references/template.md")


def _skills_root(project: Path) -> Path:
    return project / ".agents" / "skills"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A git-less project with one native skill recorded in the manifest."""
    repo_root = tmp_path / "project"
    native = _skills_root(repo_root) / "using-reinicorn"
    native.mkdir(parents=True)
    (native / "SKILL.md").write_text("# using-reinicorn\n")
    write_manifest(repo_root, version="0.0.0")
    return repo_root


@pytest.fixture
def installed(project: Path, tmp_path: Path, fake_skillset_fetch, monkeypatch) -> Path:
    """Install the demo adapter, then chdir so `demo` resolves by name."""
    adapter_dir = tmp_path / "demo"
    adapter_dir.mkdir()
    (adapter_dir / "adapter.yaml").write_text(DEMO_YAML)
    installer.install_adapter(
        load_adapter(adapter_dir), project, cache_dir=tmp_path / "cache"
    )
    fake_skillset_fetch.clear()
    monkeypatch.chdir(tmp_path)
    return project


# --- missing_files -----------------------------------------------------------


def test_missing_files_lists_absent_lock_entries_sorted(installed: Path) -> None:
    lock = read_lock(installed)
    assert lock is not None
    (_skills_root(installed) / SCRATCH).unlink()
    (_skills_root(installed) / BETA_TEMPLATE).unlink()

    assert missing_files(installed, lock) == [
        SCRATCH.as_posix(), BETA_TEMPLATE.as_posix(),
    ]


def test_missing_files_treats_a_dangling_symlink_as_present(installed: Path) -> None:
    """Whatever someone put at the path — even a broken link — is theirs to keep."""
    lock = read_lock(installed)
    assert lock is not None
    target = _skills_root(installed) / SCRATCH
    target.unlink()
    target.symlink_to("nowhere")

    assert missing_files(installed, lock) == []


# --- restore_from_lock --------------------------------------------------------


def test_restore_writes_only_the_missing_files(
    installed: Path, fake_skillset_fetch
) -> None:
    """Missing files come back byte-identical to the lock; a locally edited
    sibling is neither overwritten nor allowed to block the restore."""
    lock = read_lock(installed)
    assert lock is not None
    root = _skills_root(installed)
    (root / SCRATCH).unlink()
    (root / BETA_TEMPLATE).unlink()
    (root / ALPHA).write_text("# my local edit\n")

    restored = restore_from_lock(installed, lock, cache_dir=installed / "cache")

    assert restored == [SCRATCH.as_posix(), BETA_TEMPLATE.as_posix()]
    assert sha256_file(root / SCRATCH) == lock.files[SCRATCH.as_posix()]
    assert sha256_file(root / BETA_TEMPLATE) == lock.files[BETA_TEMPLATE.as_posix()]
    assert (root / ALPHA).read_text() == "# my local edit\n"
    # The lock is the record; restore must not rewrite it.
    assert read_lock(installed) == lock
    # One fetch, verified against the lock's own digest.
    assert [c["expected_digest"] for c in fake_skillset_fetch] == [lock.archive_sha256]


def test_restore_regenerates_the_wiring_doc_and_link(installed: Path) -> None:
    """A fresh clone has neither; restore is the only thing that brings them back."""
    lock = read_lock(installed)
    assert lock is not None
    (_skills_root(installed) / SCRATCH).unlink()
    wiring_doc_path(installed).unlink()
    (installed / ".claude" / "skills").unlink()

    restore_from_lock(installed, lock, cache_dir=installed / "cache")

    assert "alpha" in wiring_doc_path(installed).read_text()
    assert (installed / ".claude" / "skills").is_symlink()


def test_restore_with_nothing_missing_does_not_fetch(
    installed: Path, fake_skillset_fetch
) -> None:
    lock = read_lock(installed)
    assert lock is not None

    assert restore_from_lock(installed, lock, cache_dir=installed / "cache") == []
    assert fake_skillset_fetch == []


def test_restore_refuses_when_the_lock_is_stale(installed: Path) -> None:
    """The adapter now stages a different file than the lock recorded: that
    is an update, not a restore — refuse, write nothing, point at update."""
    lock = read_lock(installed)
    assert lock is not None
    root = _skills_root(installed)
    (root / SCRATCH).unlink()
    stale = SkillsetLock(
        adapter=lock.adapter, repo=lock.repo, commit=lock.commit,
        archive_sha256=lock.archive_sha256,
        files={**lock.files, SCRATCH.as_posix(): "0" * 64},
        wiring=lock.wiring,
    )
    write_lock(installed, stale)

    with pytest.raises(AdapterError, match="rcorn skills update"):
        restore_from_lock(installed, stale, cache_dir=installed / "cache")
    assert not (root / SCRATCH).exists()


def test_restore_refuses_when_the_adapter_source_repo_moved(installed: Path) -> None:
    lock = read_lock(installed)
    assert lock is not None
    (_skills_root(installed) / SCRATCH).unlink()
    moved = SkillsetLock(
        adapter=lock.adapter, repo="acme/elsewhere", commit=lock.commit,
        archive_sha256=lock.archive_sha256, files=lock.files, wiring=lock.wiring,
    )
    write_lock(installed, moved)

    with pytest.raises(AdapterError, match="acme/elsewhere"):
        restore_from_lock(installed, moved, cache_dir=installed / "cache")


def test_restore_unresolvable_adapter_name_errors(
    installed: Path, monkeypatch, tmp_path: Path
) -> None:
    lock = read_lock(installed)
    assert lock is not None
    (_skills_root(installed) / SCRATCH).unlink()
    monkeypatch.chdir(tmp_path / "project")  # no ./demo here

    with pytest.raises(AdapterError, match="not a bundled adapter"):
        restore_from_lock(installed, lock, cache_dir=installed / "cache")


# --- ensure_adapter_files -----------------------------------------------------


def test_ensure_without_a_lock_is_a_silent_no_op(project: Path, capsys) -> None:
    assert ensure_adapter_files(project) is RestoreOutcome.NO_LOCK
    assert capsys.readouterr().out == ""


def test_ensure_with_everything_present_is_silent(installed: Path, capsys) -> None:
    capsys.readouterr()
    assert ensure_adapter_files(installed) is RestoreOutcome.COMPLETE
    assert capsys.readouterr().out == ""


def test_ensure_restores_and_reports(installed: Path, capsys) -> None:
    root = _skills_root(installed)
    (root / SCRATCH).unlink()
    capsys.readouterr()

    outcome = ensure_adapter_files(installed, cache_dir=installed / "cache")

    assert outcome is RestoreOutcome.RESTORED
    assert (root / SCRATCH).is_file()
    out = capsys.readouterr().out
    assert "1 " in out and "missing" in out
    assert "Restored" in out and "demo" in out


def test_ensure_reports_a_failed_restore_without_raising(
    installed: Path, monkeypatch, capsys
) -> None:
    """A hook or `rcorn update` must carry on — the files can be restored later."""
    from reinicorn.skillset import restore as restore_mod

    (_skills_root(installed) / SCRATCH).unlink()

    def offline(*_args, **_kwargs):
        raise AdapterError("Failed to fetch acme/skills: offline.\n  How to fix: reconnect.")

    monkeypatch.setattr(restore_mod, "fetch_source", offline)
    capsys.readouterr()

    outcome = ensure_adapter_files(installed, cache_dir=installed / "cache")

    assert outcome is RestoreOutcome.FAILED
    out = capsys.readouterr().out
    assert "offline" in out
    assert "rcorn skills install" in out
