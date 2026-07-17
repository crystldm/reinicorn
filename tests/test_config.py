"""Tests for reins.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from reinicorn.config import config_get, config_set, kb_scope


def test_reads_value(tmp_path: Path):
    cfg = tmp_path / ".reinicorn-config"
    cfg.write_text('FOO=bar\nBAZ="qux"\n')
    assert config_get("FOO", root=tmp_path) == "bar"
    assert config_get("BAZ", root=tmp_path) == "qux"


def test_missing_key_returns_default(tmp_path: Path):
    cfg = tmp_path / ".reinicorn-config"
    cfg.write_text("FOO=bar\n")
    assert config_get("MISSING", "default_val", root=tmp_path) == "default_val"


def test_missing_file_returns_default(tmp_path: Path):
    assert config_get("FOO", "fallback", root=tmp_path) == "fallback"


def test_comments_and_blanks_ignored(tmp_path: Path):
    cfg = tmp_path / ".reinicorn-config"
    cfg.write_text("# comment\n\nFOO=bar\n  \n")
    assert config_get("FOO", root=tmp_path) == "bar"


def test_single_quoted_value(tmp_path: Path):
    cfg = tmp_path / ".reinicorn-config"
    cfg.write_text("FOO='hello world'\n")
    assert config_get("FOO", root=tmp_path) == "hello world"


def test_value_with_equals(tmp_path: Path):
    cfg = tmp_path / ".reinicorn-config"
    cfg.write_text("PATTERN=[A-Z]+-[0-9]+\n")
    assert config_get("PATTERN", root=tmp_path) == "[A-Z]+-[0-9]+"


def test_kb_scope_prefers_configured_scope(tmp_path: Path) -> None:
    (tmp_path / ".reinicorn-config").write_text(
        "REINICORN_KB_SCOPE=reinicorn\n"
    )
    assert kb_scope(tmp_path) == "reinicorn"


def test_kb_scope_rejects_invalid_configured_scope(tmp_path: Path, capsys) -> None:
    """An unsafe configured scope fails closed rather than being trusted."""
    (tmp_path / ".reinicorn-config").write_text(
        "REINICORN_KB_SCOPE=../escape\n"
    )
    with pytest.raises(SystemExit):
        kb_scope(tmp_path)
    assert "Invalid REINICORN_KB_SCOPE" in capsys.readouterr().out


def test_config_set_appends_missing_key_and_preserves_existing_content(
    tmp_path: Path,
) -> None:
    config = tmp_path / ".reinicorn-config"
    config.write_text("# Repository settings\n\nOTHER=value")

    config_set("REINICORN_KB_SCOPE", "reinicorn", tmp_path)

    lines = config.read_text().splitlines()
    # New key is appended as the last line...
    assert lines[-1] == "REINICORN_KB_SCOPE=reinicorn"
    # ...and every pre-existing line is preserved unchanged and in order...
    assert lines[:-1] == ["# Repository settings", "", "OTHER=value"]
    # ...with the missing trailing newline normalized in.
    assert config.read_text().endswith("\n")


def test_config_set_replaces_existing_key_and_preserves_unrelated_content(
    tmp_path: Path,
) -> None:
    config = tmp_path / ".reinicorn-config"
    config.write_text(
        "# Repository settings\n"
        "REINICORN_KB_SCOPE=old-scope\n"
        "\n"
        "OTHER=value\n"
        "  # Keep this comment\n"
        "\n"
    )

    config_set("REINICORN_KB_SCOPE", "reinicorn", tmp_path)

    result = config.read_text()
    lines = result.splitlines()
    # Existing key is replaced in place — same position, exactly once, old value gone.
    assert lines[1] == "REINICORN_KB_SCOPE=reinicorn"
    assert lines.count("REINICORN_KB_SCOPE=reinicorn") == 1
    assert "old-scope" not in result
    # Unrelated lines (comment, blank lines, other key, indented comment) untouched.
    assert lines[0] == "# Repository settings"
    assert lines[2:] == ["", "OTHER=value", "  # Keep this comment", ""]
