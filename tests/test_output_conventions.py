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


def test_stderr_confinement_is_ruff_enforced():
    """The stderr channel rule is ruff-native; this pins the config.

    `sys.stderr` outside console.py is banned via TID251 (per the ruff-first
    philosophy in test_source_of_truth.py — stronger than the string scan
    this test replaced: whole src tree, and it catches `from sys import
    stderr` too). A config edit could silently drop the ban; this pin makes
    that a test failure instead.
    """
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    lint = tomllib.loads(pyproject.read_text())["tool"]["ruff"]["lint"]

    assert "sys.stderr" in lint["flake8-tidy-imports"]["banned-api"], (
        "the sys.stderr TID251 ban is gone — stderr writes outside "
        "console.py are no longer linted"
    )
    exempt = [
        path for path, rules in lint["per-file-ignores"].items()
        if "TID251" in rules and path.startswith("src/")
    ]
    assert sorted(exempt) == [
        "src/reinicorn/console.py",
        "src/reinicorn/kb.py",
    ], (
        "unexpected TID251 exemption in src/ — a new entry would also lift "
        f"the stderr ban for that module (found: {exempt})"
    )
    # kb.py's exemption exists for sanitize_branch, but TID251 is per-rule:
    # it lifts the stderr ban there too. Ruff can't see that, so pin it here.
    kb_src = (pyproject.parent / "src" / "reinicorn" / "kb.py").read_text()
    assert "sys.stderr" not in kb_src and "from sys import stderr" not in kb_src, (
        "kb.py writes to stderr directly — its TID251 exemption is for "
        "sanitize_branch only; route output through console.py"
    )
