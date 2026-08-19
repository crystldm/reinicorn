"""Tests for reinicorn.skillset.fetch."""

from __future__ import annotations

import io
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import pytest

from reinicorn.manifest import sha256_file
from reinicorn.skillset import fetch
from reinicorn.skillset.adapter import AdapterError, AdapterSource

TEST_COMMIT = "1234567890abcdef1234567890abcdef12345678"
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "upstream-tree"


def make_source(commit: str = TEST_COMMIT) -> AdapterSource:
    return AdapterSource(repo="acme/skills", commit=commit, annotation="v1.0.0")


def build_fixture_tarball(dest_dir: Path, sha: str) -> Path:
    """Pack tests/skillset/fixtures/upstream-tree into a codeload-shaped tar.gz."""
    tar_path = dest_dir / "fixture.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(FIXTURE_ROOT, arcname=f"skills-{sha}")
    return tar_path


def build_malicious_tarball(dest_dir: Path) -> Path:
    """A tarball with a path-traversal member, rejected by filter="data".

    A plain absolute member name (e.g. "/abs/evil.txt") is silently
    re-rooted under the destination by tarfile's "data" filter (leading
    slashes are stripped, then the sanitized path is checked) rather than
    rejected — see cpython tarfile._get_filtered_attrs. A member that
    resolves outside the destination after normalization (e.g. a leading
    "../") is what filter="data" actually refuses, raising
    tarfile.OutsideDestinationError (a tarfile.TarError subclass).
    """
    tar_path = dest_dir / "evil.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        data = b"evil"
        info = tarfile.TarInfo(name="../evil.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return tar_path


def test_fetch_source_extracts_tree_and_returns_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tar_path = build_fixture_tarball(tmp_path, TEST_COMMIT)
    monkeypatch.setattr(fetch, "tarball_url", lambda _source: f"file://{tar_path}")
    source = make_source()
    cache_dir = tmp_path / "cache"

    tree_root, digest = fetch.fetch_source(source, cache_dir)

    assert tree_root.is_dir()
    assert (tree_root / "skills" / "alpha" / "SKILL.md").read_text() == (
        FIXTURE_ROOT / "skills" / "alpha" / "SKILL.md"
    ).read_text()
    assert (
        tree_root / "skills" / "nested" / "beta" / "references" / "template.md"
    ).is_file()
    assert digest == sha256_file(tar_path)


def test_fetch_source_second_call_hits_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tar_path = build_fixture_tarball(tmp_path, TEST_COMMIT)
    monkeypatch.setattr(fetch, "tarball_url", lambda _source: f"file://{tar_path}")
    source = make_source()
    cache_dir = tmp_path / "cache"

    first_root, first_digest = fetch.fetch_source(source, cache_dir)
    tar_path.unlink()  # the "network" source is now gone

    second_root, second_digest = fetch.fetch_source(source, cache_dir)

    assert second_digest == first_digest
    assert (second_root / "skills" / "alpha" / "SKILL.md").is_file()
    assert second_root != first_root  # fresh extraction dir each call


def test_fetch_source_digest_mismatch_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tar_path = build_fixture_tarball(tmp_path, TEST_COMMIT)
    monkeypatch.setattr(fetch, "tarball_url", lambda _source: f"file://{tar_path}")
    source = make_source()
    cache_dir = tmp_path / "cache"
    expected = "0" * 64

    with pytest.raises(AdapterError) as exc_info:
        fetch.fetch_source(source, cache_dir, expected_digest=expected)

    message = str(exc_info.value)
    assert expected in message
    assert sha256_file(tar_path) in message


def test_fetch_source_rejects_absolute_path_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tar_path = build_malicious_tarball(tmp_path)
    monkeypatch.setattr(fetch, "tarball_url", lambda _source: f"file://{tar_path}")
    source = make_source()
    cache_dir = tmp_path / "cache"

    with pytest.raises(AdapterError) as exc_info:
        fetch.fetch_source(source, cache_dir)

    message = str(exc_info.value)
    assert "acme/skills" in message or str(cache_dir) in message


def test_download_passes_a_timeout_to_urlopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stalled connection must not hang forever (no timeout = indefinite wait)."""
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class FakeResponse(io.BytesIO):
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *exc_info: object) -> None:
            self.close()

    def fake_urlopen(*args: object, **kwargs: object) -> FakeResponse:
        calls.append((args, kwargs))
        return FakeResponse(b"data")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    source = make_source()
    cache_path = tmp_path / "cache.tar.gz"

    fetch._download(source, cache_path)

    assert len(calls) == 1
    _args, kwargs = calls[0]
    assert kwargs.get("timeout") == fetch._DOWNLOAD_TIMEOUT_SECONDS


def test_tarball_url_matches_codeload_shape() -> None:
    source = make_source()
    assert fetch.tarball_url(source) == (
        f"https://codeload.github.com/acme/skills/tar.gz/{TEST_COMMIT}"
    )


def test_default_cache_dir_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom = tmp_path / "custom-reinicorn-cache"
    monkeypatch.setenv("REINICORN_CACHE_DIR", str(custom))
    assert fetch.default_cache_dir() == custom


def test_default_cache_dir_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REINICORN_CACHE_DIR", raising=False)
    assert fetch.default_cache_dir() == (
        Path.home() / ".cache" / "reinicorn" / "skillsets"
    )


def test_extraction_failure_removes_temp_dir_corrupt_tarball(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt tarball extraction failure should not leave behind a temp dir."""
    # Create a corrupt (truncated) tarball
    tar_path = tmp_path / "corrupt.tar.gz"
    tar_path.write_bytes(b"PK\x03\x04")  # Incomplete gzip/tar data

    monkeypatch.setattr(fetch, "tarball_url", lambda _source: f"file://{tar_path}")
    source = make_source()
    cache_dir = tmp_path / "cache"

    # Snapshot temp dirs before extraction attempt
    temp_root = Path(tempfile.gettempdir())
    dirs_before = {
        d.name for d in temp_root.iterdir() if d.name.startswith("reinicorn-skillset-")
    }

    with pytest.raises(AdapterError):
        fetch.fetch_source(source, cache_dir)

    # Assert no new reinicorn-skillset-* dirs were created
    dirs_after = {
        d.name for d in temp_root.iterdir() if d.name.startswith("reinicorn-skillset-")
    }
    assert dirs_after == dirs_before, f"Temp dir was not cleaned up: {dirs_after - dirs_before}"


def test_extraction_failure_removes_temp_dir_malicious_tarball(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malicious tarball extraction failure should not leave behind a temp dir."""
    tar_path = build_malicious_tarball(tmp_path)
    monkeypatch.setattr(fetch, "tarball_url", lambda _source: f"file://{tar_path}")
    source = make_source()
    cache_dir = tmp_path / "cache"

    # Snapshot temp dirs before extraction attempt
    temp_root = Path(tempfile.gettempdir())
    dirs_before = {
        d.name for d in temp_root.iterdir() if d.name.startswith("reinicorn-skillset-")
    }

    with pytest.raises(AdapterError):
        fetch.fetch_source(source, cache_dir)

    # Assert no new reinicorn-skillset-* dirs were created
    dirs_after = {
        d.name for d in temp_root.iterdir() if d.name.startswith("reinicorn-skillset-")
    }
    assert dirs_after == dirs_before, f"Temp dir was not cleaned up: {dirs_after - dirs_before}"


def test_extraction_failure_removes_temp_dir_invalid_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invalid tarball structure (no single top-level dir) should clean up temp."""
    # Create a tarball with multiple top-level entries
    tar_path = tmp_path / "invalid-structure.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        info1 = tarfile.TarInfo(name="file1.txt")
        info1.size = 5
        tar.addfile(info1, io.BytesIO(b"hello"))
        info2 = tarfile.TarInfo(name="file2.txt")
        info2.size = 5
        tar.addfile(info2, io.BytesIO(b"world"))

    monkeypatch.setattr(fetch, "tarball_url", lambda _source: f"file://{tar_path}")
    source = make_source()
    cache_dir = tmp_path / "cache"

    # Snapshot temp dirs before extraction attempt
    temp_root = Path(tempfile.gettempdir())
    dirs_before = {
        d.name for d in temp_root.iterdir() if d.name.startswith("reinicorn-skillset-")
    }

    with pytest.raises(AdapterError):
        fetch.fetch_source(source, cache_dir)

    # Assert no new reinicorn-skillset-* dirs were created
    dirs_after = {
        d.name for d in temp_root.iterdir() if d.name.startswith("reinicorn-skillset-")
    }
    assert dirs_after == dirs_before, f"Temp dir was not cleaned up: {dirs_after - dirs_before}"
