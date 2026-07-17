"""Tests for the agent guardrail hook that blocks raw git in kb/."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run_hook(tool_input: dict) -> subprocess.CompletedProcess:
    """Run the guardrail hook with the given tool input."""
    hook = Path("editor-hooks/block-raw-kb-git.sh")
    payload = json.dumps({"tool_name": "Bash", "tool_input": tool_input})
    return subprocess.run(
        ["bash", str(hook)],
        input=payload,
        capture_output=True,
        text=True,
    )


def test_blocks_git_in_kb_dir():
    """Hook should block git commands that cd into kb/."""
    r = _run_hook({"command": "cd kb && git add -A"})
    assert r.returncode == 2
    assert "Reinicorn" in r.stderr
    assert "rcorn kb publish" in r.stderr


def test_blocks_git_with_cwd_kb():
    """Hook should block git -C kb/ commands."""
    r = _run_hook({"command": "git -C kb/ status"})
    assert r.returncode == 2


def test_blocks_git_with_relative_kb():
    """Hook should block git -C ./kb commands."""
    r = _run_hook({"command": "git -C ./kb status"})
    assert r.returncode == 2


def test_blocks_git_with_semicolon():
    """Hook should block cd kb;git (semicolon separator)."""
    r = _run_hook({"command": "cd kb;git push origin main"})
    assert r.returncode == 2


def test_blocks_pushd_kb():
    """Hook should block pushd kb && git commands."""
    r = _run_hook({"command": "pushd kb && git status"})
    assert r.returncode == 2


def test_allows_normal_git():
    """Hook should allow git commands not targeting kb/."""
    r = _run_hook({"command": "git status"})
    assert r.returncode == 0


def test_allows_non_git_commands():
    """Hook should allow non-git commands."""
    r = _run_hook({"command": "ls -la"})
    assert r.returncode == 0


def test_allows_rcorn_commands():
    """Hook should allow rcorn kb git commands."""
    r = _run_hook({"command": "uv run rcorn kb git status"})
    assert r.returncode == 0


def test_blocks_raw_kb_git_after_separate_rcorn_command():
    """A separate rcorn command must not exempt raw kb Git."""
    r = _run_hook({"command": "uv run rcorn --version; git -C kb status"})
    assert r.returncode == 2


def test_blocks_raw_kb_git_when_rcorn_is_an_argument():
    """An argument containing rcorn must not exempt raw kb Git."""
    r = _run_hook({"command": "git -C kb status rcorn"})
    assert r.returncode == 2


def test_blocks_raw_kb_git_when_rcorn_is_in_a_comment():
    """A comment containing rcorn must not exempt raw kb Git."""
    r = _run_hook({"command": "cd kb && git status # rcorn"})
    assert r.returncode == 2


def test_blocks_raw_kb_git_when_rcorn_is_echoed():
    """Echoing rcorn must not exempt raw kb Git."""
    r = _run_hook({"command": "echo rcorn && cd kb && git status"})
    assert r.returncode == 2


def test_allows_non_bash_tools():
    """Hook should ignore non-Bash tool calls."""
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "kb/foo.md"}})
    hook = Path("editor-hooks/block-raw-kb-git.sh")
    r = subprocess.run(
        ["bash", str(hook)],
        input=payload,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
