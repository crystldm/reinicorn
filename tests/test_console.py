"""Tests for reins.console."""

from __future__ import annotations

from reinicorn import console


def test_info_prints_undecorated_when_not_tty(capsys):
    console.info("hello")
    assert capsys.readouterr().out == "hello\n"


def test_success_no_color_when_not_tty(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    console.success("ok")
    out = capsys.readouterr().out
    assert "ok" in out
    assert "\033[" not in out


def test_success_color_when_forced(capsys, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    console.success("ok")
    out = capsys.readouterr().out
    assert "\033[32m" in out  # green


def test_error_no_color_goes_to_stdout(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    console.error("bad")
    captured = capsys.readouterr()
    assert "error: bad" in captured.out
    assert captured.err == ""


def test_header_bold_when_forced(capsys, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    console.header("title")
    out = capsys.readouterr().out
    assert "\033[1m" in out  # bold


def test_no_color_env_overrides_force_color(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    console.success("ok")
    out = capsys.readouterr().out
    assert "\033[" not in out


def test_warn_prints_undecorated_when_not_tty(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    console.warn("careful")
    out = capsys.readouterr().out
    assert out == "careful\n"


def test_error_is_structured_and_on_stdout(capsys):
    console.error("kb not found")
    out, err = capsys.readouterr()
    assert "error: kb not found" in out
    assert err == ""


def test_progress_goes_to_stderr(capsys):
    console.progress("Publishing kb changes...")
    out, err = capsys.readouterr()
    assert out == ""
    assert "Publishing kb changes..." in err


def test_next_step_prints_one_line_per_command(capsys):
    console.next_step("reins plan create", "reins kb status")
    out, err = capsys.readouterr()
    assert out == "next: reins plan create\nnext: reins kb status\n"
    assert err == ""


def test_indentation_when_tty(capsys, monkeypatch):
    monkeypatch.setattr(console, "_is_tty", lambda: True)
    console.info("x")
    out, _ = capsys.readouterr()
    assert out == "  x\n"
