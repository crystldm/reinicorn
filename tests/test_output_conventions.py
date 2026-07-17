"""Mechanical enforcement of the axi output conventions (spec §6).

Channel model: stdout = data/errors/suggestions, stderr = progress/debug,
exit codes = status. These tests are the lint that spec §6 requires before
the convention can become a golden principle.
"""

from reinicorn import console


def test_error_channel_and_shape(capsys):
    console.error("boom")
    out, err = capsys.readouterr()
    assert out.startswith("error: boom")
    assert err == ""


def test_progress_channel(capsys):
    console.progress("working...")
    out, err = capsys.readouterr()
    assert out == ""
    assert err == "working...\n"


def test_next_step_shape(capsys):
    console.next_step("reins plan create")
    out, err = capsys.readouterr()
    assert out == "next: reins plan create\n"
    assert err == ""


def test_no_direct_stderr_prints_in_commands():
    """Agent-facing modules must use console.* channels, not raw stderr prints."""
    from pathlib import Path

    import reinicorn.commands as commands

    offenders = []
    for py in Path(commands.__path__[0]).rglob("*.py"):
        text = py.read_text()
        if "file=sys.stderr" in text:
            offenders.append(py.name)
    assert offenders == [], f"raw stderr prints in: {offenders}"
