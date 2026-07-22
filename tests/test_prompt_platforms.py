"""Unit tests for honest select-set platform prompt (spec: honest-init-platform-prompt)."""

from __future__ import annotations

from unittest.mock import patch

from hypothesis import example, given
from hypothesis import strategies as st

from reinicorn.commands import init_platforms as platforms_mod


def _run(user_input: str, capsys) -> tuple[list[str], str]:
    with patch("builtins.input", return_value=user_input):
        result = platforms_mod._prompt_platforms()
    captured = capsys.readouterr()
    # console.warn/print both go to stdout today
    return result, captured.out


def test_prompt_has_no_checkbox_markers(capsys):
    result, out = _run("", capsys)
    assert result == ["claude"]
    assert "[x]" not in out
    assert "[ ]" not in out


def test_prompt_uses_select_wording_not_toggle(capsys):
    _, out = _run("", capsys)
    lower = out.lower()
    assert "select" in lower
    assert "default" in lower
    assert "toggle" not in lower


def test_empty_enter_defaults_no_warning(capsys):
    result, out = _run("", capsys)
    assert result == ["claude"]
    assert "discard" not in out.lower()
    assert "ignored" not in out.lower()


def test_select_2_is_cursor_only(capsys):
    result, _ = _run("2", capsys)
    assert result == ["cursor"]


def test_select_1_2(capsys):
    result, _ = _run("1,2", capsys)
    assert result == ["claude", "cursor"]


def test_parse_platform_selection_orders_keys_and_discards_invalid_tokens():
    parser = getattr(platforms_mod, "_parse_platform_selection", None)
    assert parser is not None

    selected, discarded = parser("2, 1, 2, nope, 9")

    assert selected == ["claude", "cursor"]
    assert discarded == ["nope", "9"]


@given(st.text(max_size=100))
@example("²")
def test_parse_platform_selection_handles_arbitrary_text(raw: str):
    selected, discarded = platforms_mod._parse_platform_selection(raw)

    expected_indices: set[int] = set()
    expected_discarded: list[str] = []
    for token in (part.strip() for part in raw.strip().split(",")):
        if not token:
            continue
        if token.isascii() and token.isdecimal():
            index = int(token) - 1
            if 0 <= index < len(platforms_mod.PLATFORM_SPECS):
                expected_indices.add(index)
                continue
        expected_discarded.append(token)

    assert selected == [
        spec.key
        for index, spec in enumerate(platforms_mod.PLATFORM_SPECS)
        if index in expected_indices
    ]
    assert discarded == expected_discarded


def test_out_of_range_9_defaults_with_warning(capsys):
    result, out = _run("9", capsys)
    assert result == ["claude"]
    assert "9" in out


def test_dedup_2_2(capsys):
    result, _ = _run("2,2", capsys)
    assert result == ["cursor"]


def test_order_2_1_is_option_list_order(capsys):
    result, _ = _run("2,1", capsys)
    assert result == ["claude", "cursor"]


def test_abc_defaults_with_warning(capsys):
    result, out = _run("abc", capsys)
    assert result == ["claude"]
    assert "abc" in out


def test_1_abc_keeps_claude_warns(capsys):
    result, out = _run("1,abc", capsys)
    assert result == ["claude"]
    assert "abc" in out


def test_2_comma_space_3(capsys):
    result, out = _run("2, 3", capsys)
    assert result == ["cursor", "copilot"]
    assert "discard" not in out.lower()
    assert "ignored" not in out.lower()


def test_2_space_3_not_fused_to_23(capsys):
    result, out = _run("2 3", capsys)
    assert result == ["claude"]
    assert "2 3" in out
