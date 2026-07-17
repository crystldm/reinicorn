"""rcorn feedback — open a GitHub issue on the reinicorn repo."""

from __future__ import annotations

import contextlib
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import webbrowser
from pathlib import Path

from reinicorn import __version__, console
from reinicorn.meta import reinicorn_source_repo
from reinicorn.mode import get_mode

_EDITOR_TEMPLATE = """\

<!-- Reinicorn Feedback
     The first line above becomes the issue title (max 80 chars).
     Everything after it becomes the issue body/description.
     Save and close the editor to submit. Leave empty to cancel. -->
"""


def _get_editor() -> str | None:
    return os.environ.get("VISUAL") or os.environ.get("EDITOR")


def _read_from_editor() -> str | None:
    editor = _get_editor()
    if not editor or not sys.stdin.isatty():
        return None
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="reinicorn-feedback-", delete=False,
    ) as f:
        f.write(_EDITOR_TEMPLATE)
        path = f.name
    try:
        cmd = [*shlex.split(editor), path]
        r = subprocess.run(cmd, check=False)
        if r.returncode != 0:
            return None
        return Path(path).read_text().strip() or None
    finally:
        with contextlib.suppress(OSError):
            Path(path).unlink(missing_ok=True)


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _parse_editor_content(content: str) -> tuple[str, str]:
    """First non-empty line = title, rest = description. HTML comments stripped."""
    cleaned = _HTML_COMMENT_RE.sub("", content)
    lines = cleaned.splitlines()
    first_idx = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first_idx is None:
        return ("", "")
    title = lines[first_idx].strip()[:80]
    rest = "\n".join(lines[first_idx + 1 :]).strip()
    return (title, rest)


def cmd_feedback(text: str | None = None) -> int:
    if text is None:
        print()
        console.header("Reinicorn Feedback")
        print()
        content = _read_from_editor()
        if content is not None:
            title, description = _parse_editor_content(content)
            if not title:
                console.error("Feedback text cannot be empty.")
                return 1
            body = _build_issue_body(description or title)
            return _open_issue(title, body)
        text = input("Describe the issue or idea: ").strip()
        if not text:
            console.error("Feedback text cannot be empty.")
            return 1

    title = text[:80]
    body = _build_issue_body(text)
    return _open_issue(title, body)


def _build_issue_body(description: str) -> str:
    mode = get_mode()
    py_version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    lines = [
        "## Description",
        "",
        description,
        "",
        "## Environment",
        "",
        f"- reinicorn: {__version__}",
        f"- Python: {py_version}",
        f"- OS: {platform.system()} {platform.release()}",
        f"- Mode: {mode}",
    ]
    return "\n".join(lines)


def _open_issue(title: str, body: str) -> int:
    repo_slug = reinicorn_source_repo()
    if repo_slug is None:
        console.error(
            "cannot derive the reinicorn repo from package metadata "
            "(Project-URL: Repository) — nowhere to file feedback"
        )
        return 1
    if shutil.which("gh"):
        r = subprocess.run(
            ["gh", "issue", "create",
             "--repo", repo_slug,
             "--title", title,
             "--body", body],
            check=False,
        )
        if r.returncode == 0:
            console.success("Issue created.")
            return 0
        console.warn("gh failed — falling back to browser.")

    params = urllib.parse.urlencode({
        "title": title, "body": body,
    })
    url = f"https://github.com/{repo_slug}/issues/new?{params}"
    console.info(f"Opening: {url}")
    _open_browser(url)
    console.success("Opened issue form in browser.")
    return 0


def _open_browser(url: str) -> None:
    """Open URL in the default browser, suppressing toolkit noise (GTK, etc.)."""
    if sys.platform == "linux" and shutil.which("xdg-open"):
        subprocess.Popen(
            ["xdg-open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        webbrowser.open(url)
