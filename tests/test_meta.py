"""Tests for reins.meta — package self-knowledge (repo home from metadata)."""

from __future__ import annotations

from reinicorn import meta


def test_reinicorn_source_repo_from_metadata(monkeypatch):
    class FakeMd:
        def get_all(self, key):
            assert key == "Project-URL"
            return ["Repository, https://github.com/acme/reins-fork"]

    monkeypatch.setattr(meta, "_load_metadata", lambda: FakeMd())
    assert meta.reinicorn_source_repo() == "acme/reins-fork"


def test_reinicorn_source_repo_none_without_repository_url(monkeypatch):
    class EmptyMd:
        def get_all(self, _key):
            return []

    monkeypatch.setattr(meta, "_load_metadata", lambda: EmptyMd())
    assert meta.reinicorn_source_repo() is None
