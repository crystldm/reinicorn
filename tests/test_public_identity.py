"""Structural tests for the Reinicorn source repository identity."""

from __future__ import annotations

import re
from pathlib import Path

import bashlex
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "test.yml",
    ROOT / ".github" / "workflows" / "lint-kb.yml",
    ROOT / ".github" / "workflows" / "lint-architecture.yml",
)

def _workflow_run_scripts(
    contents: str, *, context: str = "workflow"
) -> list[str]:
    """Return string run values from executable GitHub Actions job steps."""
    document = yaml.safe_load(contents)
    scripts: list[str] = []

    if not isinstance(document, dict):
        return scripts
    jobs = document.get("jobs")
    if not isinstance(jobs, dict):
        return scripts
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step_number, step in enumerate(steps, start=1):
            if not isinstance(step, dict) or "run" not in step:
                continue
            run = step["run"]
            assert isinstance(run, str), (
                f"{context}: job {job_name}: step {step_number}: "
                "run must be a string"
            )
            scripts.append(run)

    return scripts


TARGET_COMMANDS = {"rcorn", "pytest", "ruff", "pyright", "python", "python3"}
COMMAND_WRAPPERS = {"env", "command", "time", "/usr/bin/time"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
TIME_COMMAND = re.compile(r"(?<![A-Za-z0-9_$\\])time(?=\s)")
SIMPLE_ARITHMETIC_EXPANSION = re.compile(r"\$\(\([^()$`\n]*\)\)")
DYNAMIC_SHELL_WORD = "\0dynamic-shell-word"


def _command_nodes(node: object) -> list[object]:
    nodes: list[object] = []
    if getattr(node, "kind", None) == "command":
        nodes.append(node)
    for value in getattr(node, "__dict__", {}).values():
        if isinstance(value, list):
            for child in value:
                if hasattr(child, "kind"):
                    nodes.extend(_command_nodes(child))
        elif hasattr(value, "kind"):
            nodes.extend(_command_nodes(value))
    return nodes


def _skip_options(words: list[str], index: int, *, wrapper: str) -> int:
    options_with_values = {
        "env": {"-u", "--unset", "-C", "--chdir"},
        "time": {"-o", "--output", "-f", "--format"},
    }.get(wrapper, set())
    while index < len(words):
        word = words[index]
        if word == "--":
            return index + 1
        if not word.startswith("-") or word == "-":
            return index
        option = word.split("=", 1)[0]
        index += 1
        if option in options_with_values and "=" not in word:
            index += 1
    return index


def _static_shell_word(source_word: str) -> str:
    """Decode one shell word, rejecting values requiring shell expansion."""
    decoded: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(source_word):
        character = source_word[index]
        if quote is None and character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if quote == character:
            quote = None
            index += 1
            continue
        if character == "\\" and quote != "'":
            if index + 1 == len(source_word):
                raise AssertionError("shell word ends with an incomplete escape")
            escaped = source_word[index + 1]
            if quote == '"' and escaped not in {'$', '`', '"', "\\", "\n"}:
                decoded.append(character)
            elif escaped != "\n":
                decoded.append(escaped)
            index += 2
            continue
        if quote != "'" and character in {"$", "`"}:
            raise AssertionError(
                "env argument expansion cannot be determined statically"
            )
        decoded.append(character)
        index += 1
    if quote is not None:
        raise AssertionError("shell word contains an unterminated quote")
    return "".join(decoded)


def _env_split_words(
    split_string: str, *, environment: dict[str, str] | None = None
) -> list[str]:
    """Split one GNU env -S argument without interpreting it as shell source."""
    words: list[str] = []
    current: list[str] = []
    quote: str | None = None
    started = False
    index = 0

    def finish_word() -> None:
        nonlocal started
        if started:
            words.append("".join(current))
            current.clear()
            started = False

    escapes = {"f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
    while index < len(split_string):
        character = split_string[index]
        if quote is None and character in " \t\n\r\v\f":
            finish_word()
            index += 1
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
                started = True
                index += 1
                continue
            if quote == character:
                quote = None
                index += 1
                continue
        if quote is None and character == "#" and not started:
            break
        if character == "\\":
            if index + 1 == len(split_string):
                raise AssertionError("env split-string ends with an incomplete escape")
            escaped = split_string[index + 1]
            if quote == "'" and escaped not in {"'", "\\"}:
                current.extend((character, escaped))
                started = True
                index += 2
                continue
            if escaped == "c" and quote is None:
                break
            if escaped == "_":
                if quote == '"':
                    current.append(" ")
                    started = True
                elif quote is None:
                    finish_word()
                else:
                    current.extend((character, escaped))
                    started = True
                index += 2
                continue
            if escaped in escapes:
                current.append(escapes[escaped])
            elif escaped in {"#", "$", '"', "'", "\\"}:
                current.append(escaped)
            else:
                raise AssertionError(
                    f"env split-string contains unsupported escape \\{escaped}"
                )
            started = True
            index += 2
            continue
        if character == "$" and quote != "'":
            match = re.match(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", split_string[index:])
            if match is None:
                raise AssertionError(
                    "env split-string supports only ${VARNAME} variable expansion"
                )
            variable = match.group(1)
            if environment is None or variable not in environment:
                raise AssertionError(
                    f"env split-string variable ${{{variable}}} is not statically defined"
                )
            current.append(environment[variable])
            started = True
            index += len(match.group(0))
            continue
        current.append(character)
        started = True
        index += 1

    if quote is not None:
        raise AssertionError("env split-string contains an unterminated quote")
    finish_word()
    return words


def _env_command_words(
    words: list[str],
    *,
    environment: dict[str, str] | None = None,
    split_depth: int = 0,
    expansion_environment: dict[str, str] | None = None,
    resolved_environment: dict[str, str] | None = None,
) -> list[str] | None:
    if split_depth > 8:
        raise AssertionError("env split-string nesting exceeds the supported limit")
    if environment is None:
        environment = {}
    if expansion_environment is None:
        expansion_environment = environment.copy()
    if resolved_environment is None:
        resolved_environment = environment.copy()

    index = 0
    while index < len(words):
        word = words[index]
        if word == "-":
            index += 1
            continue
        if word == "--":
            index += 1
            break
        if ASSIGNMENT.match(word) or not word.startswith("-"):
            break
        if word == "-S" or word == "--split-string":
            if index + 1 >= len(words):
                return None
            split_string = words[index + 1]
            remainder = words[index + 2 :]
            expanded = (
                _env_split_words(split_string, environment=expansion_environment)
                + remainder
            )
            return _env_command_words(
                expanded,
                environment=environment,
                split_depth=split_depth + 1,
                expansion_environment=expansion_environment,
                resolved_environment=resolved_environment,
            )
        if word.startswith("--split-string="):
            expanded = _env_split_words(
                word.split("=", 1)[1], environment=expansion_environment
            ) + words[index + 1 :]
            return _env_command_words(
                expanded,
                environment=environment,
                split_depth=split_depth + 1,
                expansion_environment=expansion_environment,
                resolved_environment=resolved_environment,
            )
        if word in {"--help", "--version"}:
            return None
        if word.startswith("--"):
            option = word.split("=", 1)[0]
            index += 1
            if option in {"--unset", "--chdir"}:
                value = word.split("=", 1)[1] if "=" in word else None
                if "=" not in word:
                    if index >= len(words):
                        return None
                    value = words[index]
                    index += 1
                if option == "--unset" and value is not None:
                    resolved_environment.pop(value, None)
                continue
            if option not in {
                "--ignore-environment",
                "--null",
                "--debug",
                "--block-signal",
                "--default-signal",
                "--ignore-signal",
                "--list-signal-handling",
            }:
                return None
            if option == "--ignore-environment":
                resolved_environment.clear()
            continue
        if not word.startswith("--"):
            short_options = word[1:]
            for option_index, option in enumerate(short_options):
                if option == "S":
                    split_string = short_options[option_index + 1 :]
                    if split_string:
                        remainder = words[index + 1 :]
                    elif index + 1 < len(words):
                        split_string = words[index + 1]
                        remainder = words[index + 2 :]
                    else:
                        return None
                    expanded = (
                        _env_split_words(
                            split_string, environment=expansion_environment
                        )
                        + remainder
                    )
                    return _env_command_words(
                        expanded,
                        environment=environment,
                        split_depth=split_depth + 1,
                        expansion_environment=expansion_environment,
                        resolved_environment=resolved_environment,
                    )
                if option in {"u", "C"}:
                    value = short_options[option_index + 1 :] or None
                    if value is None:
                        index += 1
                        if index >= len(words):
                            return None
                        value = words[index]
                    if option == "u":
                        resolved_environment.pop(value, None)
                    break
                if option not in {"i", "0", "v"}:
                    return None
                if option == "i":
                    resolved_environment.clear()
            index += 1
            continue

    while index < len(words) and ASSIGNMENT.match(words[index]):
        name, value = words[index].split("=", 1)
        resolved_environment[name] = value
        index += 1
    environment.clear()
    environment.update(resolved_environment)
    return words[index:] or None


def _reaches_env_executable(words: list[str]) -> bool:
    """Return whether wrapper resolution reaches env as the executable."""
    index = 0
    while index < len(words):
        word = words[index]
        if ASSIGNMENT.match(word):
            index += 1
            continue
        if word not in COMMAND_WRAPPERS:
            return False
        wrapper = "time" if word == "/usr/bin/time" else word
        if wrapper == "env":
            return True
        if wrapper == "command":
            for option in words[index + 1 :]:
                if option == "--" or not option.startswith("-"):
                    break
                if "v" in option[1:] or "V" in option[1:]:
                    return False
        index = _skip_options(words, index + 1, wrapper=wrapper)
    return False


def _shell_word_is_dynamic(
    part: object, *, arithmetic_expansions: list[tuple[int, int]]
) -> bool:
    if getattr(part, "parts", []):
        return True
    start, end = part.pos
    return any(
        expansion_start < end and start < expansion_end
        for expansion_start, expansion_end in arithmetic_expansions
    )


def _dynamic_shell_word_placeholder(word: str) -> str:
    if ASSIGNMENT.match(word):
        return f"{word.split('=', 1)[0]}={DYNAMIC_SHELL_WORD}"
    return DYNAMIC_SHELL_WORD


def _executable_words(
    command: object,
    *,
    source: str,
    arithmetic_expansions: list[tuple[int, int]],
) -> list[str] | None:
    word_parts = [part for part in command.parts if part.kind == "word"]
    use_static_words = _reaches_env_executable([part.word for part in word_parts])
    words = [
        _dynamic_shell_word_placeholder(part.word)
        if any(
            expansion_start < part.pos[1] and part.pos[0] < expansion_end
            for expansion_start, expansion_end in arithmetic_expansions
        )
        else (
            _static_shell_word(source[part.pos[0] : part.pos[1]])
            if use_static_words
            else (
                _dynamic_shell_word_placeholder(part.word)
                if _shell_word_is_dynamic(
                    part, arithmetic_expansions=arithmetic_expansions
                )
                else part.word
            )
        )
        for part in word_parts
    ]
    environment: dict[str, str] = {}
    if use_static_words:
        for part in command.parts:
            if part.kind == "word":
                break
            if part.kind != "assignment":
                continue
            assignment = _static_shell_word(source[part.pos[0] : part.pos[1]])
            name, value = assignment.split("=", 1)
            environment[name] = value
    index = 0
    while index < len(words):
        word = words[index]
        if ASSIGNMENT.match(word):
            index += 1
            continue
        if DYNAMIC_SHELL_WORD in word:
            # The executable (or a wrapper preceding it) resolves from a runtime
            # value we cannot read statically, so we cannot prove it is a bare
            # project command. Treat it as undeterminable rather than a violation:
            # legitimate dynamic dispatch such as `"$test_file"` in
            # lint-architecture.yml must not be flagged.
            return None
        if word not in COMMAND_WRAPPERS:
            return words[index:]
        wrapper = "time" if word == "/usr/bin/time" else word
        if wrapper == "env":
            resolved = _env_command_words(
                words[index + 1 :], environment=environment
            )
            if resolved is None:
                return None
            words = resolved
            index = 0
            continue
        if wrapper == "command":
            for option in words[index + 1 :]:
                if option == "--" or not option.startswith("-"):
                    break
                if "v" in option[1:] or "V" in option[1:]:
                    return None
        index = _skip_options(words, index + 1, wrapper=wrapper)
    return None


def _bare_project_command(
    script: str, *, context: str = "run script"
) -> tuple[int, str] | None:
    arithmetic_expansions = [
        match.span() for match in SIMPLE_ARITHMETIC_EXPANSION.finditer(script)
    ]
    parser_input = SIMPLE_ARITHMETIC_EXPANSION.sub(
        lambda match: "0".ljust(len(match.group())), script
    )
    # bashlex also rejects Bash's [[ ... ]] conditional command. Turning its
    # delimiters into the equivalent-length [ ... ] form preserves expansions
    # (including command substitutions) for AST inspection.
    parser_input = parser_input.replace("[[", "[ ").replace("]]", " ]")
    try:
        trees = bashlex.parse(parser_input)
    except NotImplementedError as error:
        if "time command" not in str(error):
            raise AssertionError(f"{context}: shell parsing failed: {error}") from error
        # bashlex has no AST implementation for Bash's reserved `time` command.
        # Escaping only that token makes it an ordinary command word for the parser.
        try:
            trees = bashlex.parse(TIME_COMMAND.sub(r"\\time", parser_input))
        except (NotImplementedError, bashlex.errors.ParsingError) as retry_error:
            message = f"{context}: shell parsing failed: {retry_error}"
            raise AssertionError(message) from retry_error
    except bashlex.errors.ParsingError as error:
        raise AssertionError(f"{context}: shell parsing failed: {error}") from error

    for tree in trees:
        for command in _command_nodes(tree):
            try:
                executable_words = _executable_words(
                    command,
                    source=parser_input,
                    arithmetic_expansions=arithmetic_expansions,
                )
            except AssertionError as error:
                raise AssertionError(f"{context}: {error}") from error
            if executable_words is None:
                continue
            executable = executable_words[0]
            if executable == "uv" and executable_words[1:2] == ["run"]:
                continue
            if executable in TARGET_COMMANDS:
                line_number = script.count("\n", 0, command.pos[0]) + 1
                return line_number, executable
    return None


def test_workflow_run_script_checks_cover_yaml_forms_and_command_boundaries() -> None:
    workflow = """\
jobs:
  test:
    steps:
      - run: uv run pytest tests/
      - run: |
          # pytest in a comment is not a command
          echo "python appears only as an argument"
          uv run rcorn kb lint
      - run: >-
          uv run
          pyright src/reinicorn
      - run: "pytest tests/"
      - run: 'ruff check src/reinicorn'
      - run: "uv run python -c \\\"print('double quoted')\\\""
      - run: 'uv run python -c "print(''single quoted'')"'
      - run: "pytest tests/" # double-quoted bare command
      - run: 'ruff check src/reinicorn' # single-quoted bare command
      - run: "uv run python -c \\\"print('# double quoted')\\\"" # trailing comment
      - run: 'uv run python -c "print(''# single quoted'')"' # trailing comment
"""

    scripts = _workflow_run_scripts(workflow)

    assert scripts == [
        "uv run pytest tests/",
        "\n".join(
            (
                "# pytest in a comment is not a command",
                'echo "python appears only as an argument"',
                "uv run rcorn kb lint",
            )
        )
        + "\n",
        "uv run pyright src/reinicorn",
        "pytest tests/",
        "ruff check src/reinicorn",
        'uv run python -c "print(\'double quoted\')"',
        'uv run python -c "print(\'single quoted\')"',
        "pytest tests/",
        "ruff check src/reinicorn",
        'uv run python -c "print(\'# double quoted\')"',
        'uv run python -c "print(\'# single quoted\')"',
    ]
    assert all(_bare_project_command(script) is None for script in scripts[:3])
    assert _bare_project_command(scripts[3]) == (1, "pytest")
    assert _bare_project_command(scripts[4]) == (1, "ruff")
    assert all(_bare_project_command(script) is None for script in scripts[5:7])
    assert _bare_project_command(scripts[7]) == (1, "pytest")
    assert _bare_project_command(scripts[8]) == (1, "ruff")
    assert all(_bare_project_command(script) is None for script in scripts[9:])
    for command in ("rcorn", "pytest", "ruff", "pyright", "python", "python3"):
        assert _bare_project_command(command) == (1, command)


def test_workflow_run_scripts_use_yaml_scalar_semantics() -> None:
    workflow = '''\
jobs:
  test:
    steps:
      - run: >-
          uv run
            pytest tests/
      - run: "pytest \\x74ests/"
'''

    scripts = _workflow_run_scripts(workflow)

    assert scripts == ["uv run\n  pytest tests/", "pytest tests/"]
    assert _bare_project_command(scripts[0]) == (2, "pytest")
    assert _bare_project_command(scripts[1]) == (1, "pytest")


def test_workflow_run_scripts_collect_only_executable_job_steps() -> None:
    workflow = """\
run: root metadata
jobs:
  lint:
    strategy:
      matrix:
        include:
          - run: matrix data
    env:
      run: job metadata
    steps:
      - uses: acme/lint@v1
        with:
          run: pytest tests/
          nested:
            run: [pytest]
      - run: uv run ruff check src/reinicorn tests
      - uses: acme/report@v1
  test:
    steps:
      - name: ordinary metadata
        metadata:
          run: false
      - run: uv run pytest tests/
  publish:
    name: no steps here
"""

    assert _workflow_run_scripts(workflow) == [
        "uv run ruff check src/reinicorn tests",
        "uv run pytest tests/",
    ]


def test_workflow_run_scripts_reject_non_string_executable_steps_with_context() -> None:
    workflow = "jobs: {test: {steps: [{uses: acme/test@v1}, {run: [pytest]}]}}"

    with pytest.raises(
        AssertionError,
        match=r"synthetic\.yml: job test: step 2: run must be a string",
    ):
        _workflow_run_scripts(workflow, context="synthetic.yml")


@pytest.mark.parametrize(
    "script, expected",
    (
        ("FOO=1 pytest tests/", (1, "pytest")),
        ("env FOO=1 pytest tests/", (1, "pytest")),
        ("env -i FOO=1 pytest tests/", (1, "pytest")),
        ("env -S pytest", (1, "pytest")),
        ('env -S "pytest --version"', (1, "pytest")),
        ("env -Spytest", (1, "pytest")),
        ('env -S"pytest --version"', (1, "pytest")),
        ("env -iSpytest", (1, "pytest")),
        ('env -iS "FOO=1 pytest"', (1, "pytest")),
        ("env -SFOO=1 pytest tests/", (1, "pytest")),
        ("env -S FOO=1 pytest tests/", (1, "pytest")),
        ("env -iS FOO=1 pytest tests/", (1, "pytest")),
        ("env -S-i pytest tests/", (1, "pytest")),
        ('env -S "-u FOO" pytest tests/', (1, "pytest")),
        ('env -iS "-C ." pytest tests/', (1, "pytest")),
        ('env -S "--unset=FOO --chdir=." pytest tests/', (1, "pytest")),
        ("env -S -- pytest tests/", (1, "pytest")),
        ("env -S-- pytest tests/", (1, "pytest")),
        ('env -S "-S \'-i pytest tests/\'"', (1, "pytest")),
        ('env -S "-S \'-i\'" pytest tests/', (1, "pytest")),
        ("COMMAND=pytest env -i -S'${COMMAND} --version'", (1, "pytest")),
        ("COMMAND=pytest env -u COMMAND -S'${COMMAND} --version'", (1, "pytest")),
        ("env --split-string=pytest", (1, "pytest")),
        ("command pytest tests/", (1, "pytest")),
        ("command -p pytest tests/", (1, "pytest")),
        ("time pytest tests/", (1, "pytest")),
        ("time -p pytest tests/", (1, "pytest")),
        ("/usr/bin/time -p pytest tests/", (1, "pytest")),
        ('echo "$(pytest --version)"', (1, "pytest")),
        ('echo "$(env -S pytest)"', (1, "pytest")),
    ),
)
def test_bare_project_command_finds_executables_after_shell_prefixes(
    script: str, expected: tuple[int, str]
) -> None:
    assert _bare_project_command(script) == expected


@pytest.mark.parametrize(
    "script",
    (
        'echo env "$HOME"',
        'printf "%s %s" "env" "$DYNAMIC"',
        'printf "%s" "$DYNAMIC"',
    ),
)
def test_bare_project_command_does_not_apply_env_decoding_to_arguments(
    script: str,
) -> None:
    assert _bare_project_command(script) is None


@pytest.mark.parametrize(
    "script",
    (
        "$CMD tests/",
        '"$CMD" tests/',
        "${CMD} tests/",
        '"${CMD}" tests/',
        "$WRAPPER -S pytest",
        'command "$CMD" tests/',
        'time "$CMD" tests/',
        '/usr/bin/time "$CMD" tests/',
        '$(printf pytest) tests/',
        "$((1 + 1)) tests/",
    ),
)
def test_bare_project_command_allows_dynamic_executable_positions(
    script: str,
) -> None:
    # A dynamic executable position cannot be proven to be a bare project
    # command, so the scanner allows it instead of failing closed. This keeps
    # legitimate dynamic dispatch (e.g. `"$test_file"` in lint-architecture.yml)
    # from being reported as a violation.
    assert _bare_project_command(script, context="synthetic workflow: run script 1") is None


def test_bare_project_command_still_fails_closed_on_env_dynamic_arguments() -> None:
    # `env` resolves its arguments through static decoding, which cannot read a
    # runtime expansion. That path stays fail-closed even though a plain dynamic
    # executable position is allowed above.
    with pytest.raises(
        AssertionError,
        match=r"synthetic workflow: run script 1: .*expansion cannot be determined",
    ):
        _bare_project_command('env "$CMD" tests/', context="synthetic workflow: run script 1")


def test_bare_project_command_allows_dynamic_arguments_to_literal_executables() -> None:
    assert _bare_project_command('echo "$CMD"') is None


@pytest.mark.parametrize(
    "script",
    (
        "COMMAND=pytest env -S'${COMMAND} --version'",
        "COMMAND=pytest command env -S'${COMMAND} --version'",
        "COMMAND=pytest time env -S'${COMMAND} --version'",
        "COMMAND=pytest /usr/bin/time env -S'${COMMAND} --version'",
    ),
)
def test_bare_project_command_applies_env_decoding_at_executable_positions(
    script: str,
) -> None:
    assert _bare_project_command(script) == (1, "pytest")


@pytest.mark.parametrize(
    "script",
    (
        'echo "then pytest is discussed"',
        "FOO=1 uv run pytest tests/",
        "env FOO=1 uv run pytest tests/",
        'env -S "uv run pytest tests/"',
        'env -S"uv run pytest tests/"',
        'env -iS"uv run pytest tests/"',
        'env -iS "uv run pytest tests/"',
        "env -SFOO=1 uv run pytest tests/",
        "env -S FOO=1 uv run pytest tests/",
        "env -iS FOO=1 uv run pytest tests/",
        'env -S "-u FOO" uv run pytest tests/',
        'env -iS "-C ." uv run pytest tests/',
        'env -S "--unset=FOO --chdir=." uv run pytest tests/',
        "env -S -- uv run pytest tests/",
        "env -S-- uv run pytest tests/",
        'env -S "-S \'-i uv run pytest tests/\'"',
        'env -S "-S \'-i\'" uv run pytest tests/',
        'env -S\'printf "ok; pytest tests/"\'',
        "COMMAND=pytest env -S\"'\\${COMMAND}' --version\"",
        "env -SFOO=1 printf 'ok; pytest tests/'",
        'env --split-string="uv run pytest tests/"',
        "command uv run pytest tests/",
        "command -v pytest",
        "command -V pytest",
        "command -pv pytest",
        "time -p uv run pytest tests/",
    ),
)
def test_bare_project_command_ignores_arguments_and_uv_run_targets(script: str) -> None:
    assert _bare_project_command(script) is None


def test_bare_project_command_fails_closed_with_context_on_invalid_shell() -> None:
    with pytest.raises(AssertionError, match="synthetic workflow: run script 1"):
        _bare_project_command("if then", context="synthetic workflow: run script 1")


def test_bare_project_command_fails_closed_on_excessive_env_split_nesting() -> None:
    with pytest.raises(AssertionError, match="env split-string nesting"):
        _env_command_words(["-S"] * 11 + ["pytest"])


def test_env_split_words_expand_only_from_explicit_environment() -> None:
    environment = {"COMMAND": "pytest"}

    assert _env_split_words("${COMMAND} --version", environment=environment) == [
        "pytest",
        "--version",
    ]
    assert _env_split_words('"${COMMAND}" --version', environment=environment) == [
        "pytest",
        "--version",
    ]


def test_env_split_words_keep_single_quoted_variables_literal() -> None:
    assert _env_split_words(
        "'${COMMAND}' --version", environment={"COMMAND": "pytest"}
    ) == ["${COMMAND}", "--version"]


def test_env_split_words_ignore_ambient_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REINICORN_STRUCTURAL_COMMAND", "pytest")

    with pytest.raises(AssertionError, match="REINICORN_STRUCTURAL_COMMAND"):
        _env_split_words("${REINICORN_STRUCTURAL_COMMAND}", environment={})


def test_bare_project_command_uses_static_leading_assignment_for_env_split() -> None:
    assert _bare_project_command(
        "COMMAND=pytest env -S'${COMMAND} --version'"
    ) == (1, "pytest")


@pytest.mark.parametrize(
    "script",
    (
        "env -S'${REINICORN_UNKNOWN_COMMAND}'",
        "SOURCE=pytest COMMAND=$SOURCE env -S'${COMMAND}'",
        "COMMAND=pytest env -i env -S'${COMMAND}'",
    ),
)
def test_bare_project_command_fails_closed_on_dynamic_env_split_values(
    script: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REINICORN_UNKNOWN_COMMAND", "pytest")

    with pytest.raises(AssertionError, match="synthetic workflow: run script 1"):
        _bare_project_command(script, context="synthetic workflow: run script 1")


def test_source_agents_identifies_reinicorn_and_uses_rcorn() -> None:
    agents = (ROOT / "AGENTS.md").read_text()
    normalized_agents = " ".join(agents.split())

    assert "UNPOPULATED" not in agents
    assert agents.startswith("# Reinicorn\n")
    assert "kb/reinicorn/README.md" in agents
    # Docs assume rcorn is installed globally, not invoked through uv.
    assert "Use `rcorn` for every KB operation" in normalized_agents
    assert "uv run reins" not in agents


def test_repository_config_uses_final_identity_and_scope() -> None:
    config_path = ROOT / ".reinicorn-config"

    assert config_path.is_file()
    config = config_path.read_text()
    assert "REINICORN_KB_SCOPE=reinicorn" in config.splitlines()
    # Owner-agnostic on purpose: this test ships in both the private source repo
    # (mnbiehl remote) and the public export (different org), so assert the kb
    # repo *name* is reinicorn-kb (never reins-kb), not a specific owner.
    assert "reinicorn-kb.git" in config
    assert not re.search(r"REINS_|\.reins|(?<![A-Za-z])reins(?![A-Za-z])", config)
    assert not (ROOT / ".reins-config").exists()


def test_gitignore_uses_final_generated_and_state_paths() -> None:
    gitignore = (ROOT / ".gitignore").read_text().splitlines()

    assert "src/reinicorn/_version.py" in gitignore
    assert ".reinicorn/mode" in gitignore
    assert "src/reins/_version.py" not in gitignore


def test_workflows_use_final_identity_and_uv_entrypoints() -> None:
    for workflow in WORKFLOWS:
        contents = workflow.read_text()
        assert not re.search(r"(?<![A-Za-z])reins(?![A-Za-z])", contents), workflow
        assert ".reins" not in contents, workflow
        assert "REINS_" not in contents, workflow
        scripts = _workflow_run_scripts(contents, context=str(workflow))
        assert scripts, f"{workflow}: expected at least one run script"
        for script_number, script in enumerate(scripts, start=1):
            context = f"{workflow}: run script {script_number}"
            violation = _bare_project_command(script, context=context)
            assert violation is None, (
                f"{workflow}: run script {script_number}, line {violation[0]} invokes "
                f"bare {violation[1]}; use 'uv run {violation[1]}'"
            )

    lint_kb = (ROOT / ".github" / "workflows" / "lint-kb.yml").read_text()
    assert "uv run rcorn kb lint" in lint_kb

    test_workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text()
    assert "uv run ruff check src/reinicorn tests" in test_workflow
    assert "uv run pyright src/reinicorn" in test_workflow
