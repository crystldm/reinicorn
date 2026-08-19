"""Tests for reinicorn.skillset.installer."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from reinicorn.identity import (
    CONFIG_FILE_NAME,
    SKILLSET_LOCK_FILE_NAME,
    STATE_DIR_NAME,
)
from reinicorn.manifest import sha256_file, write_manifest
from reinicorn.skillset import installer
from reinicorn.skillset.adapter import Adapter, AdapterError, load_adapter
from reinicorn.skillset.lockfile import read_lock

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "upstream-tree"

COMMIT_A = "0123456789abcdef0123456789abcdef01234567"
COMMIT_B = "89abcdef0123456789abcdef0123456789abcdef"
DIGESTS = {COMMIT_A: "a" * 64, COMMIT_B: "b" * 64}

ATTRIBUTION = "Adapted from acme/skills.\n"

BASE_YAML = f"""\
name: demo
source:
  repo: acme/skills
  commit: {COMMIT_A}
  annotation: v1.0.0
skills:
  skills/alpha: alpha
  skills/nested/beta: beta
files:
  ATTRIBUTION.md: files/ATTRIBUTION.md
wiring:
  spec: [alpha]
"""

# Same adapter, next upstream pin, with alpha/scratch.md dropped.
DROPS_SCRATCH_YAML = f"""\
name: demo
source:
  repo: acme/skills
  commit: {COMMIT_B}
  annotation: v1.1.0
skills:
  skills/alpha: alpha
  skills/nested/beta: beta
excludes:
  - skills/alpha/scratch.md
files:
  ATTRIBUTION.md: files/ATTRIBUTION.md
wiring:
  spec: [alpha]
"""

# Same adapter, next pin, with the whole beta skill dropped.
DROPS_BETA_YAML = f"""\
name: demo
source:
  repo: acme/skills
  commit: {COMMIT_B}
  annotation: v1.1.0
skills:
  skills/alpha: alpha
files:
  ATTRIBUTION.md: files/ATTRIBUTION.md
wiring:
  spec: [alpha]
"""

# Installs its alpha skill under the native skill's name.
CLASHES_WITH_NATIVE_YAML = f"""\
name: demo
source:
  repo: acme/skills
  commit: {COMMIT_A}
  annotation: v1.0.0
skills:
  skills/alpha: using-reinicorn
"""

# Declares the reinicorn-generated wiring doc as one of its own files.
CLAIMS_WIRING_DOC_YAML = f"""\
name: demo
source:
  repo: acme/skills
  commit: {COMMIT_A}
  annotation: v1.0.0
skills:
  skills/alpha: alpha
files:
  using-reinicorn/references/skillset-wiring.md: files/ATTRIBUTION.md
wiring:
  spec: [alpha]
"""

OTHER_ADAPTER_YAML = f"""\
name: other
source:
  repo: acme/skills
  commit: {COMMIT_A}
  annotation: v1.0.0
skills:
  skills/alpha: alpha
"""

EXTRA_FILES = {"files/ATTRIBUTION.md": ATTRIBUTION}

STAGED_PATHS = frozenset({
    "alpha/SKILL.md",
    "alpha/scratch.md",
    "beta/SKILL.md",
    "beta/references/template.md",
    "ATTRIBUTION.md",
})

WIRING_DOC_REL = "using-reinicorn/references/skillset-wiring.md"


def make_adapter(
    root: Path, yaml_text: str, extra_files: dict[str, str] | None = None
) -> Adapter:
    """Write an adapter dir (adapter.yaml plus referenced files) and load it."""
    root.mkdir(parents=True)
    (root / "adapter.yaml").write_text(yaml_text)
    for rel, content in (extra_files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return load_adapter(root)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A git-less project with one native skill recorded in the manifest."""
    repo_root = tmp_path / "project"
    native = repo_root / ".agents" / "skills" / "using-reinicorn"
    native.mkdir(parents=True)
    (native / "SKILL.md").write_text("# using-reinicorn\n\nNative skill.\n")
    write_manifest(repo_root, version="0.0.0")
    return repo_root


@pytest.fixture
def fetch_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Replace installer.fetch_source with a local fixture-tree copier.

    Each call extracts a fresh copy of the upstream fixture into its own
    temp directory, exactly like the real fetch — so the installer's
    temp-tree cleanup is exercised without touching the network.
    """
    calls: list[dict[str, object]] = []

    def fake_fetch(
        source, cache_dir: Path, *, expected_digest: str | None = None
    ) -> tuple[Path, str]:
        parent = Path(tempfile.mkdtemp(prefix="reinicorn-test-fetch-"))
        tree = parent / f"acme-skills-{source.commit[:7]}"
        shutil.copytree(FIXTURE_ROOT, tree)
        calls.append({
            "commit": source.commit,
            "expected_digest": expected_digest,
            "cache_dir": cache_dir,
            "parent": parent,
        })
        return tree, DIGESTS[source.commit]

    monkeypatch.setattr(installer, "fetch_source", fake_fetch)
    return calls


def snapshot(root: Path) -> dict[str, str]:
    """Every path under *root*: files by sha256, dirs and symlinks by marker."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        for name in dirnames + filenames:
            path = here / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                out[rel] = f"symlink:{path.readlink()}"
            elif path.is_dir():
                out[rel] = "dir"
            else:
                out[rel] = sha256_file(path)
    return out


def skills_snapshot(repo_root: Path) -> dict[str, str]:
    return snapshot(repo_root / ".agents" / "skills")


def install_base(project: Path, tmp_path: Path, name: str = "adapter") -> Adapter:
    adapter = make_adapter(tmp_path / name, BASE_YAML, EXTRA_FILES)
    installer.install_adapter(adapter, project, cache_dir=tmp_path / "cache")
    return adapter


# --- maintain_link ---------------------------------------------------------


def test_maintain_link_creates_relative_symlink(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "project"
    (repo_root / ".agents" / "skills").mkdir(parents=True)

    installer.maintain_link(repo_root)

    link = repo_root / ".claude" / "skills"
    assert link.is_symlink()
    assert str(link.readlink()) == "../.agents/skills"
    assert "Linked .claude/skills -> .agents/skills" in capsys.readouterr().out


def test_maintain_link_honours_configured_paths(tmp_path: Path) -> None:
    repo_root = tmp_path / "project"
    (repo_root / "custom" / "skills").mkdir(parents=True)
    (repo_root / CONFIG_FILE_NAME).write_text(
        "REINICORN_SKILLS_DIR=custom/skills\nREINICORN_SKILLS_LINK=.claude/skills\n"
    )

    installer.maintain_link(repo_root)

    assert str((repo_root / ".claude" / "skills").readlink()) == "../custom/skills"


def test_maintain_link_disabled_is_a_no_op(tmp_path: Path) -> None:
    repo_root = tmp_path / "project"
    (repo_root / ".agents" / "skills").mkdir(parents=True)
    (repo_root / CONFIG_FILE_NAME).write_text("REINICORN_SKILLS_LINK=none\n")

    installer.maintain_link(repo_root)

    assert not (repo_root / ".claude").exists()


def test_maintain_link_leaves_real_directory_in_place(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "project"
    (repo_root / ".agents" / "skills").mkdir(parents=True)
    real = repo_root / ".claude" / "skills"
    real.mkdir(parents=True)
    (real / "mine.md").write_text("hand-written\n")

    installer.maintain_link(repo_root)

    assert not real.is_symlink()
    assert (real / "mine.md").read_text() == "hand-written\n"
    out = capsys.readouterr().out
    assert ".claude/skills already exists as a real directory — left in place." in out


def test_maintain_link_skips_when_the_skills_dir_is_missing(
    tmp_path: Path, capsys
) -> None:
    """A configured-but-absent skills dir must not yield a dangling link."""
    repo_root = tmp_path / "project"
    repo_root.mkdir(parents=True)
    (repo_root / CONFIG_FILE_NAME).write_text(
        "REINICORN_SKILLS_DIR=custom/skills\nREINICORN_SKILLS_LINK=.claude/skills\n"
    )

    installer.maintain_link(repo_root)

    link = repo_root / ".claude" / "skills"
    assert not link.is_symlink()
    assert not link.exists()
    out = capsys.readouterr().out
    assert "custom/skills" in out
    assert "REINICORN_SKILLS_DIR" in out


def test_maintain_link_leaves_existing_symlink_alone(tmp_path: Path) -> None:
    repo_root = tmp_path / "project"
    (repo_root / ".agents" / "skills").mkdir(parents=True)
    link = repo_root / ".claude" / "skills"
    link.parent.mkdir(parents=True)
    link.symlink_to("elsewhere", target_is_directory=True)

    installer.maintain_link(repo_root)

    assert str(link.readlink()) == "elsewhere"


def test_init_link_helper_delegates_to_maintain_link(tmp_path: Path) -> None:
    from reinicorn.commands import init

    repo_root = tmp_path / "project"
    (repo_root / ".agents" / "skills").mkdir(parents=True)

    init._link_claude_skills(repo_root)

    assert str((repo_root / ".claude" / "skills").readlink()) == "../.agents/skills"


# --- install ---------------------------------------------------------------


def test_fresh_install_writes_skills_lock_wiring_and_link(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)

    skills = project / ".agents" / "skills"
    for rel in STAGED_PATHS:
        assert (skills / rel).is_file(), rel
    assert (skills / "ATTRIBUTION.md").read_text() == ATTRIBUTION
    # Native skill untouched.
    assert (skills / "using-reinicorn" / "SKILL.md").read_text().startswith(
        "# using-reinicorn"
    )
    # Wiring doc rendered from the adapter's wiring map.
    wiring_doc = (skills / WIRING_DOC_REL).read_text()
    assert "# Skillset Wiring" in wiring_doc
    assert '| spec | `rcorn spec create "<title>"` | alpha |' in wiring_doc
    # Compatibility link.
    assert str((project / ".claude" / "skills").readlink()) == "../.agents/skills"
    # Lockfile.
    lock = read_lock(project)
    assert lock is not None
    assert lock.adapter == "demo"
    assert lock.repo == "acme/skills"
    assert lock.commit == COMMIT_A
    assert lock.archive_sha256 == DIGESTS[COMMIT_A]
    assert set(lock.files) == STAGED_PATHS
    assert lock.files["ATTRIBUTION.md"] == sha256_file(skills / "ATTRIBUTION.md")
    assert lock.wiring["spec"].skills == ("alpha",)
    assert len(fetch_calls) == 1


def test_install_removes_the_fetched_temp_tree(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)

    parent = fetch_calls[0]["parent"]
    assert isinstance(parent, Path)
    assert not parent.exists()


def test_install_uses_the_given_cache_dir(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)

    assert fetch_calls[0]["cache_dir"] == tmp_path / "cache"
    assert fetch_calls[0]["expected_digest"] is None


def test_install_falls_back_to_the_default_cache_dir(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REINICORN_CACHE_DIR", str(tmp_path / "envcache"))
    adapter = make_adapter(tmp_path / "adapter", BASE_YAML, EXTRA_FILES)

    installer.install_adapter(adapter, project)

    assert fetch_calls[0]["cache_dir"] == tmp_path / "envcache"


def test_reinstalling_the_same_adapter_is_byte_identical(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path, name="adapter-1")
    before = snapshot(project)

    install_base(project, tmp_path, name="adapter-2")

    assert snapshot(project) == before


def test_reinstall_passes_the_locked_digest_for_the_same_pin(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path, name="adapter-1")
    install_base(project, tmp_path, name="adapter-2")

    assert fetch_calls[0]["expected_digest"] is None
    assert fetch_calls[1]["expected_digest"] == DIGESTS[COMMIT_A]


def test_update_to_a_new_pin_expects_no_digest(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_SCRATCH_YAML, EXTRA_FILES)

    installer.update_adapter(adapter_v2, project, cache_dir=tmp_path / "cache")

    assert fetch_calls[1]["expected_digest"] is None


def test_install_over_a_different_adapter_raises(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)
    before = snapshot(project)
    other = make_adapter(tmp_path / "other", OTHER_ADAPTER_YAML)

    with pytest.raises(AdapterError, match="demo"):
        installer.install_adapter(other, project, cache_dir=tmp_path / "cache")

    assert snapshot(project) == before


def test_collision_with_native_skill_raises_and_writes_nothing(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    before = snapshot(project)
    adapter = make_adapter(tmp_path / "adapter", CLASHES_WITH_NATIVE_YAML)

    with pytest.raises(AdapterError, match="using-reinicorn") as excinfo:
        installer.install_adapter(adapter, project, cache_dir=tmp_path / "cache")

    assert "native" in str(excinfo.value)
    assert "How to fix" in str(excinfo.value)
    assert snapshot(project) == before


def test_collision_with_unmanaged_directory_raises_and_writes_nothing(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    stray = project / ".agents" / "skills" / "alpha"
    stray.mkdir(parents=True)
    (stray / "NOTES.md").write_text("mine\n")
    before = snapshot(project)
    adapter = make_adapter(tmp_path / "adapter", BASE_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError, match="alpha") as excinfo:
        installer.install_adapter(adapter, project, cache_dir=tmp_path / "cache")

    assert "unmanaged" in str(excinfo.value)
    assert snapshot(project) == before


def test_collision_with_unmanaged_file_raises_and_writes_nothing(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    stray = project / ".agents" / "skills" / "ATTRIBUTION.md"
    stray.write_text("someone else's attribution\n")
    before = snapshot(project)
    adapter = make_adapter(tmp_path / "adapter", BASE_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError, match=re.escape("ATTRIBUTION.md")):
        installer.install_adapter(adapter, project, cache_dir=tmp_path / "cache")

    assert snapshot(project) == before


def test_adapter_claiming_the_wiring_doc_raises_and_writes_nothing(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    """Reinicorn rewrites the wiring doc itself — an adapter may not own it."""
    before = snapshot(project)
    adapter = make_adapter(tmp_path / "adapter", CLAIMS_WIRING_DOC_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError, match=re.escape(WIRING_DOC_REL)) as excinfo:
        installer.install_adapter(adapter, project, cache_dir=tmp_path / "cache")

    message = str(excinfo.value)
    assert "wiring doc" in message
    assert "How to fix" in message
    assert snapshot(project) == before


# --- rollback --------------------------------------------------------------


def test_lock_write_failure_rolls_the_whole_project_back(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = snapshot(project)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(installer, "write_lock", boom)
    adapter = make_adapter(tmp_path / "adapter", BASE_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError, match="rolled back"):
        installer.install_adapter(adapter, project, cache_dir=tmp_path / "cache")

    assert snapshot(project) == before


def test_unexpected_failure_rolls_back_and_propagates(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = snapshot(project)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("nope")

    monkeypatch.setattr(installer, "write_wiring", boom)
    adapter = make_adapter(tmp_path / "adapter", BASE_YAML, EXTRA_FILES)

    with pytest.raises(RuntimeError, match="nope"):
        installer.install_adapter(adapter, project, cache_dir=tmp_path / "cache")

    assert snapshot(project) == before


def test_failed_update_restores_the_previous_install_exactly(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_base(project, tmp_path)
    before = snapshot(project)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(installer, "write_lock", boom)
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_BETA_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError, match="rolled back"):
        installer.update_adapter(adapter_v2, project, cache_dir=tmp_path / "cache")

    assert snapshot(project) == before


def test_failed_rollback_preserves_backups_outside_the_work_dir(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restore that itself fails must not take the only copy down with it."""
    install_base(project, tmp_path)
    skills = project / ".agents" / "skills"
    victim = skills / "alpha" / "SKILL.md"
    control = skills / "beta" / "SKILL.md"
    victim.write_text("victim edit\n")
    control.write_text("control edit\n")

    real_copy = installer._copy_path

    def flaky_copy(source: Path, dest: Path) -> None:
        # Only the restore leg writes back to a project path; the backup leg
        # writes into the transaction's backup dir.
        if dest == victim:
            raise OSError("read-only file system")
        real_copy(source, dest)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(installer, "_copy_path", flaky_copy)
    monkeypatch.setattr(installer, "write_lock", boom)
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_SCRATCH_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError) as excinfo:
        installer.update_adapter(
            adapter_v2, project, force=True, cache_dir=tmp_path / "cache"
        )

    message = str(excinfo.value)
    assert "the project is unchanged" not in message
    assert str(victim) in message
    # Every other tracked path was still restored.
    assert control.read_text() == "control edit\n"

    match = re.search(r"backup: (\S+)", message)
    assert match is not None, message
    backup = Path(match.group(1))
    assert backup.is_file()
    assert backup.read_text() == "victim edit\n"
    # Durable: outside the install work dir, and named in the message.
    assert backup.parent.name.startswith("reinicorn-skillset-backup-")
    assert str(backup.parent) in message
    shutil.rmtree(backup.parent, ignore_errors=True)


def test_failed_relocation_preserves_backups_in_the_work_dir(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If preserving the backups durably itself fails (mkdtemp: disk full),
    the backups must not be lost — they must survive under work/backup,
    which the installer must then refuse to delete."""
    install_base(project, tmp_path)
    skills = project / ".agents" / "skills"
    victim = skills / "alpha" / "SKILL.md"
    control = skills / "beta" / "SKILL.md"
    victim.write_text("victim edit\n")
    control.write_text("control edit\n")

    real_copy = installer._copy_path
    real_mkdtemp = tempfile.mkdtemp

    def flaky_copy(source: Path, dest: Path) -> None:
        # Only the restore leg writes back to a project path; the backup leg
        # writes into the transaction's backup dir.
        if dest == victim:
            raise OSError("read-only file system")
        real_copy(source, dest)

    def flaky_mkdtemp(*args: object, **kwargs: object) -> str:
        prefix = kwargs.get("prefix", "")
        if isinstance(prefix, str) and prefix.startswith(
            "reinicorn-skillset-backup-"
        ):
            raise OSError("disk full")
        return real_mkdtemp(*args, **kwargs)  # type: ignore[arg-type]

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(installer, "_copy_path", flaky_copy)
    monkeypatch.setattr(installer, "write_lock", boom)
    monkeypatch.setattr(installer.tempfile, "mkdtemp", flaky_mkdtemp)
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_SCRATCH_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError) as excinfo:
        installer.update_adapter(
            adapter_v2, project, force=True, cache_dir=tmp_path / "cache"
        )

    message = str(excinfo.value)
    assert str(victim) in message
    # Every other tracked path was still restored despite the relocation failure.
    assert control.read_text() == "control edit\n"

    match = re.search(r"backup: (\S+)", message)
    assert match is not None, message
    backup = Path(match.group(1))
    # Points at work/backup (never relocated) — and it must still be on disk,
    # with the original bytes, after the call returns.
    assert backup.parent.name == "backup"
    assert str(backup.parent) in message
    assert backup.is_file()
    assert backup.read_text() == "victim edit\n"
    shutil.rmtree(backup.parent.parent, ignore_errors=True)


def test_failed_backup_relocation_preserves_the_work_dir(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If moving one backup out of the work dir fails (shutil.move: OSError),
    that backup's only surviving copy is still under work/backup — the
    installer must not delete the work dir out from under it."""
    install_base(project, tmp_path)
    skills = project / ".agents" / "skills"
    victim = skills / "alpha" / "SKILL.md"
    control = skills / "beta" / "SKILL.md"
    victim.write_text("victim edit\n")
    control.write_text("control edit\n")

    real_copy = installer._copy_path

    def flaky_copy(source: Path, dest: Path) -> None:
        # Only the restore leg writes back to a project path; the backup leg
        # writes into the transaction's backup dir.
        if dest == victim:
            raise OSError("read-only file system")
        real_copy(source, dest)

    def flaky_move(*_args: object, **_kwargs: object) -> str:
        raise OSError("disk full during relocation")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(installer, "_copy_path", flaky_copy)
    monkeypatch.setattr(installer, "write_lock", boom)
    monkeypatch.setattr(installer.shutil, "move", flaky_move)
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_SCRATCH_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError) as excinfo:
        installer.update_adapter(
            adapter_v2, project, force=True, cache_dir=tmp_path / "cache"
        )

    message = str(excinfo.value)
    assert "LOST" not in message
    assert str(victim) in message
    # Every other tracked path was still restored.
    assert control.read_text() == "control edit\n"

    match = re.search(r"backup: (\S+)", message)
    assert match is not None, message
    backup = Path(match.group(1))
    # Still lives under work/backup (never relocated) — and must survive on
    # disk after the call returns, with the original bytes.
    assert backup.parent.name == "backup"
    assert str(backup.parent) in message
    assert backup.is_file()
    assert backup.read_text() == "victim edit\n"
    shutil.rmtree(backup.parent.parent, ignore_errors=True)


def test_failed_install_removes_the_fetched_temp_tree(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(installer, "write_lock", boom)
    adapter = make_adapter(tmp_path / "adapter", BASE_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError):
        installer.install_adapter(adapter, project, cache_dir=tmp_path / "cache")

    parent = fetch_calls[0]["parent"]
    assert isinstance(parent, Path)
    assert not parent.exists()


# --- update ----------------------------------------------------------------


def test_update_without_a_lock_raises(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    before = snapshot(project)
    adapter = make_adapter(tmp_path / "adapter", BASE_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError, match="no adapter installed"):
        installer.update_adapter(adapter, project, cache_dir=tmp_path / "cache")

    assert snapshot(project) == before
    assert fetch_calls == []


def test_update_of_a_different_adapter_raises(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)
    other = make_adapter(tmp_path / "other", OTHER_ADAPTER_YAML)

    with pytest.raises(AdapterError, match="demo"):
        installer.update_adapter(other, project, cache_dir=tmp_path / "cache")


def test_update_removes_a_dropped_unmodified_file(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_SCRATCH_YAML, EXTRA_FILES)

    preserved = installer.update_adapter(
        adapter_v2, project, cache_dir=tmp_path / "cache"
    )

    assert preserved == []
    assert not (project / ".agents" / "skills" / "alpha" / "scratch.md").exists()
    lock = read_lock(project)
    assert lock is not None
    assert "alpha/scratch.md" not in lock.files
    assert lock.commit == COMMIT_B


def test_update_preserves_a_dropped_locally_modified_file(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)
    scratch = project / ".agents" / "skills" / "alpha" / "scratch.md"
    scratch.write_text("my own notes\n")
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_SCRATCH_YAML, EXTRA_FILES)

    preserved = installer.update_adapter(
        adapter_v2, project, cache_dir=tmp_path / "cache"
    )

    assert preserved == ["alpha/scratch.md"]
    assert scratch.read_text() == "my own notes\n"


def test_update_dropping_a_whole_skill_removes_its_directory(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_BETA_YAML, EXTRA_FILES)

    installer.update_adapter(adapter_v2, project, cache_dir=tmp_path / "cache")

    assert not (project / ".agents" / "skills" / "beta").exists()


def test_update_aborts_on_a_locally_modified_file_without_force(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)
    skill = project / ".agents" / "skills" / "alpha" / "SKILL.md"
    skill.write_text("locally edited\n")
    before = snapshot(project)
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_SCRATCH_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError, match=re.escape("alpha/SKILL.md")) as excinfo:
        installer.update_adapter(adapter_v2, project, cache_dir=tmp_path / "cache")

    assert "rcorn skills update --force" in str(excinfo.value)
    assert snapshot(project) == before


def test_update_aborts_when_an_owned_file_is_replaced_by_a_directory(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    """A directory silently replacing an owned file must gate like a hash
    mismatch — not sail through and get rmtree'd by the commit."""
    install_base(project, tmp_path)
    skill = project / ".agents" / "skills" / "alpha" / "SKILL.md"
    skill.unlink()
    skill.mkdir()
    (skill / "notes.txt").write_text("mine\n")
    before = snapshot(project)
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_SCRATCH_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError, match=re.escape("alpha/SKILL.md")) as excinfo:
        installer.update_adapter(adapter_v2, project, cache_dir=tmp_path / "cache")

    assert "rcorn skills update --force" in str(excinfo.value)
    assert snapshot(project) == before


def test_update_aborts_when_an_owned_file_is_replaced_by_a_dangling_symlink(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    """A (possibly dangling) symlink replacing an owned file must gate too —
    `.is_file()` is False for it, same as the directory case."""
    install_base(project, tmp_path)
    skill = project / ".agents" / "skills" / "alpha" / "SKILL.md"
    skill.unlink()
    skill.symlink_to(tmp_path / "elsewhere" / "nope.md")
    before = snapshot(project)
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_SCRATCH_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError, match=re.escape("alpha/SKILL.md")) as excinfo:
        installer.update_adapter(adapter_v2, project, cache_dir=tmp_path / "cache")

    assert "rcorn skills update --force" in str(excinfo.value)
    assert snapshot(project) == before


def test_update_with_force_overwrites_an_owned_directory_replacement(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)
    skill = project / ".agents" / "skills" / "alpha" / "SKILL.md"
    skill.unlink()
    skill.mkdir()
    (skill / "notes.txt").write_text("mine\n")
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_SCRATCH_YAML, EXTRA_FILES)

    installer.update_adapter(
        adapter_v2, project, force=True, cache_dir=tmp_path / "cache"
    )

    assert skill.is_file()
    assert skill.read_text() == (
        FIXTURE_ROOT / "skills" / "alpha" / "SKILL.md"
    ).read_text()


def test_update_with_force_overwrites_an_owned_symlink_replacement(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)
    skill = project / ".agents" / "skills" / "alpha" / "SKILL.md"
    skill.unlink()
    skill.symlink_to(tmp_path / "elsewhere" / "nope.md")
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_SCRATCH_YAML, EXTRA_FILES)

    installer.update_adapter(
        adapter_v2, project, force=True, cache_dir=tmp_path / "cache"
    )

    assert skill.is_file()
    assert not skill.is_symlink()
    assert skill.read_text() == (
        FIXTURE_ROOT / "skills" / "alpha" / "SKILL.md"
    ).read_text()


def test_update_with_force_overwrites_a_locally_modified_file(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)
    skill = project / ".agents" / "skills" / "alpha" / "SKILL.md"
    skill.write_text("locally edited\n")
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_SCRATCH_YAML, EXTRA_FILES)

    installer.update_adapter(
        adapter_v2, project, force=True, cache_dir=tmp_path / "cache"
    )

    assert skill.read_text() == (FIXTURE_ROOT / "skills" / "alpha" / "SKILL.md").read_text()


def test_update_rewrites_the_wiring_doc_from_the_new_adapter(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)
    yaml_text = DROPS_SCRATCH_YAML.replace("  spec: [alpha]", "  plan: [beta]")
    adapter_v2 = make_adapter(tmp_path / "v2", yaml_text, EXTRA_FILES)

    installer.update_adapter(adapter_v2, project, cache_dir=tmp_path / "cache")

    doc = (project / ".agents" / "skills" / WIRING_DOC_REL).read_text()
    assert "| plan | `rcorn plan create` | beta |" in doc
    lock = read_lock(project)
    assert lock is not None
    assert set(lock.wiring) == {"plan"}


def test_install_restores_a_removed_native_skill_on_rollback(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wiring doc lands inside the native skill's dir — rollback must
    leave that native skill exactly as it was."""
    before = skills_snapshot(project)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(installer, "write_lock", boom)
    adapter = make_adapter(tmp_path / "adapter", BASE_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError):
        installer.install_adapter(adapter, project, cache_dir=tmp_path / "cache")

    assert skills_snapshot(project) == before
    assert not (project / ".agents" / "skills" / WIRING_DOC_REL).exists()


def test_unknown_wiring_key_fails_before_fetching_or_writing(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    before = snapshot(project)
    yaml_text = BASE_YAML.replace("  spec: [alpha]", "  nosuchdoctype: [alpha]")
    adapter = make_adapter(tmp_path / "adapter", yaml_text, EXTRA_FILES)

    with pytest.raises(AdapterError, match="nosuchdoctype"):
        installer.install_adapter(adapter, project, cache_dir=tmp_path / "cache")

    assert snapshot(project) == before
    assert fetch_calls == []


def test_failed_install_into_an_empty_project_leaves_no_directories(
    tmp_path: Path, fetch_calls: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "bare"
    repo_root.mkdir()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(installer, "write_lock", boom)
    adapter = make_adapter(tmp_path / "adapter", BASE_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError, match="rolled back"):
        installer.install_adapter(adapter, repo_root, cache_dir=tmp_path / "cache")

    assert snapshot(repo_root) == {}


def test_link_failure_rolls_back_the_link_it_created(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = snapshot(project)

    def half_linked(repo_root: Path) -> None:
        link = repo_root / ".claude" / "skills"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to("../.agents/skills", target_is_directory=True)
        raise OSError("link went wrong")

    monkeypatch.setattr(installer, "maintain_link", half_linked)
    adapter = make_adapter(tmp_path / "adapter", BASE_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError, match="rolled back"):
        installer.install_adapter(adapter, project, cache_dir=tmp_path / "cache")

    assert not (project / ".claude" / "skills").is_symlink()
    assert snapshot(project) == before


def test_failed_update_restores_the_existing_compatibility_link(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_base(project, tmp_path)
    before = snapshot(project)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("link went wrong")

    monkeypatch.setattr(installer, "maintain_link", boom)
    adapter_v2 = make_adapter(tmp_path / "v2", DROPS_SCRATCH_YAML, EXTRA_FILES)

    with pytest.raises(AdapterError, match="rolled back"):
        installer.update_adapter(adapter_v2, project, cache_dir=tmp_path / "cache")

    assert (project / ".claude" / "skills").is_symlink()
    assert snapshot(project) == before


def test_collision_with_a_native_file_raises_and_writes_nothing(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    """A `files:` destination landing on a manifest-tracked native file."""
    before = snapshot(project)
    yaml_text = BASE_YAML.replace(
        "  ATTRIBUTION.md: files/ATTRIBUTION.md",
        "  using-reinicorn/SKILL.md: files/ATTRIBUTION.md",
    )
    adapter = make_adapter(tmp_path / "adapter", yaml_text, EXTRA_FILES)

    with pytest.raises(
        AdapterError, match=re.escape("using-reinicorn/SKILL.md")
    ) as excinfo:
        installer.install_adapter(adapter, project, cache_dir=tmp_path / "cache")

    assert "native Reinicorn skill file" in str(excinfo.value)
    assert snapshot(project) == before


def test_maintain_link_copies_when_symlinks_are_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    repo_root = tmp_path / "project"
    skills = repo_root / ".agents" / "skills"
    skills.mkdir(parents=True)
    (skills / "note.md").write_text("skill\n")

    def no_symlinks(*_args: object, **_kwargs: object) -> None:
        raise OSError("symlinks unavailable")

    monkeypatch.setattr(Path, "symlink_to", no_symlinks)

    installer.maintain_link(repo_root)

    copied = repo_root / ".claude" / "skills"
    assert not copied.is_symlink()
    assert (copied / "note.md").read_text() == "skill\n"
    assert "Symlinks unavailable" in capsys.readouterr().out


def test_lockfile_lives_under_the_state_dir(
    project: Path, tmp_path: Path, fetch_calls: list[dict[str, object]]
) -> None:
    install_base(project, tmp_path)

    assert (project / STATE_DIR_NAME / SKILLSET_LOCK_FILE_NAME).is_file()
