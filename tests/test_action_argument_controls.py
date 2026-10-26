"""Action arguments must not silently lose quality gates after a newline."""

from __future__ import annotations

import pytest

from scripts.validate_action_args import main, validate_action_args


@pytest.mark.parametrize("label", ["args", "baseline-args"])
@pytest.mark.parametrize("control", ["\r", "\n"])
def test_multiline_gate_inputs_are_rejected(label: str, control: str) -> None:
    with pytest.raises(ValueError, match="must be a single line"):
        validate_action_args(f"--max-missing 0{control}--max-duplicates 0", label)


@pytest.mark.parametrize("label", ["args", "baseline-args"])
@pytest.mark.parametrize("control", ["\x00", "\x07", "\x1b", "\x7f", "\x85", "\x9f"])
def test_terminal_controls_are_rejected(label: str, control: str) -> None:
    with pytest.raises(ValueError, match="terminal control characters"):
        validate_action_args(f"--max-missing{control}0", label)


@pytest.mark.parametrize("codepoint", range(128, 160))
def test_every_c1_control_is_rejected(codepoint: int) -> None:
    with pytest.raises(ValueError, match="terminal control characters"):
        validate_action_args(f"--max-rows{chr(codepoint)}1", "args")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "--max-missing 0",
        "--max-missing\t0 --max-duplicates\t0",
        "--require-columns año,商品 --max-missing 0",
    ],
)
def test_valid_options_remain_accepted(value: str) -> None:
    validate_action_args(value, "args")
    validate_action_args(value, "baseline-args")


@pytest.mark.parametrize(
    ("variable", "value", "error"),
    [
        ("INPUT_ARGS", "--max-missing 0\n--max-duplicates 0", "args must be a single line"),
        (
            "INPUT_BASELINE_ARGS",
            "--max-row-drop 20\r--fail-on-schema-change",
            "baseline-args must be a single line",
        ),
        ("INPUT_ARGS", "--max-missing\x1b0", "args must not contain terminal"),
        ("INPUT_BASELINE_ARGS", "--max-row-drop\x85 20", "baseline-args must not contain"),
    ],
)
def test_runner_rejects_both_option_sources(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    variable: str,
    value: str,
    error: str,
) -> None:
    monkeypatch.setenv("INPUT_ARGS", "--max-missing\t0")
    monkeypatch.setenv("INPUT_BASELINE_ARGS", "--max-row-drop 20")
    monkeypatch.setenv(variable, value)
    assert main() == 2
    assert error in capsys.readouterr().err


def test_runner_accepts_tab_delimited_single_line_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INPUT_ARGS", "--max-missing\t0")
    monkeypatch.setenv("INPUT_BASELINE_ARGS", "--max-row-drop\t20")
    assert main() == 0
