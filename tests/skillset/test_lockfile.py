"""Tests for reinicorn.skillset.lockfile."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reinicorn.skillset.adapter import WiringEntry
from reinicorn.skillset.lockfile import SkillsetLock, read_lock, write_lock


def make_lock(**overrides: Any) -> SkillsetLock:
    defaults: dict[str, Any] = {
        "adapter": "demo",
        "repo": "acme/skills",
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "archive_sha256": "a" * 64,
        "files": {"alpha/SKILL.md": "b" * 64},
        "wiring": {
            "spec": WiringEntry(skills=("alpha",)),
            "prd": WiringEntry(skills=("alpha",), optional=True),
        },
    }
    defaults.update(overrides)
    return SkillsetLock(**defaults)


def test_write_lock_creates_file_at_state_dir(tmp_path: Path) -> None:
    lock = make_lock()
    path = write_lock(tmp_path, lock)
    assert path == tmp_path / ".reinicorn" / "skillset-lock.json"
    assert path.is_file()


def test_write_lock_json_is_stable_and_sorted(tmp_path: Path) -> None:
    lock = make_lock()
    path = write_lock(tmp_path, lock)
    text = path.read_text()
    assert text.endswith("\n")
    data = json.loads(text)
    assert list(data.keys()) == sorted(data.keys())


def test_round_trip_write_read(tmp_path: Path) -> None:
    lock = make_lock()
    write_lock(tmp_path, lock)
    result = read_lock(tmp_path)
    assert result == lock


def test_round_trip_preserves_optional_flags(tmp_path: Path) -> None:
    lock = make_lock(
        wiring={
            "spec": WiringEntry(skills=("alpha", "beta"), optional=False),
            "prd": WiringEntry(skills=("gamma",), optional=True),
        }
    )
    write_lock(tmp_path, lock)
    result = read_lock(tmp_path)
    assert result is not None
    assert result.wiring["spec"].optional is False
    assert result.wiring["prd"].optional is True


def test_read_lock_returns_none_when_missing(tmp_path: Path) -> None:
    assert read_lock(tmp_path) is None


def test_read_lock_returns_none_for_invalid_json(tmp_path: Path) -> None:
    lock_dir = tmp_path / ".reinicorn"
    lock_dir.mkdir()
    (lock_dir / "skillset-lock.json").write_text("not json")
    assert read_lock(tmp_path) is None


def test_read_lock_returns_none_for_missing_keys(tmp_path: Path) -> None:
    lock_dir = tmp_path / ".reinicorn"
    lock_dir.mkdir()
    (lock_dir / "skillset-lock.json").write_text('{"adapter": "demo"}')
    assert read_lock(tmp_path) is None


def test_read_lock_returns_none_for_malformed_wiring_entry(tmp_path: Path) -> None:
    lock_dir = tmp_path / ".reinicorn"
    lock_dir.mkdir()
    data = {
        "adapter": "demo",
        "repo": "acme/skills",
        "commit": "0" * 40,
        "archive_sha256": "a" * 64,
        "files": {},
        "wiring": {"spec": {"skills": "not-a-list"}},
    }
    (lock_dir / "skillset-lock.json").write_text(json.dumps(data))
    assert read_lock(tmp_path) is None


def test_read_lock_returns_none_for_non_bool_optional(tmp_path: Path) -> None:
    lock_dir = tmp_path / ".reinicorn"
    lock_dir.mkdir()
    data = {
        "adapter": "demo",
        "repo": "acme/skills",
        "commit": "0" * 40,
        "archive_sha256": "a" * 64,
        "files": {},
        "wiring": {"spec": {"skills": ["alpha"], "optional": "yes"}},
    }
    (lock_dir / "skillset-lock.json").write_text(json.dumps(data))
    assert read_lock(tmp_path) is None


def test_read_lock_returns_none_for_non_string_file_hash(tmp_path: Path) -> None:
    lock_dir = tmp_path / ".reinicorn"
    lock_dir.mkdir()
    data = {
        "adapter": "demo",
        "repo": "acme/skills",
        "commit": "0" * 40,
        "archive_sha256": "a" * 64,
        "files": {"alpha/SKILL.md": 123},
        "wiring": {},
    }
    (lock_dir / "skillset-lock.json").write_text(json.dumps(data))
    assert read_lock(tmp_path) is None
