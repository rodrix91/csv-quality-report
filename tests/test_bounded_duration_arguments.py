"""Bound user-supplied duration options before Python integer conversion."""

from __future__ import annotations

import argparse

import pytest

from csv_quality_report.cli import _duration, main


def test_maximum_width_preserves_leading_zero_padded_duration() -> None:
    # The limit protects resource use, not a cap on calendar duration.
    assert _duration("0" * 62 + "1d") == 86_400
    assert _duration(" 7d ") == 7 * 86_400
    assert _duration("36h") == 36 * 3600


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--max-baseline-age", "9" * 65 + "d"),
        ("--max-baseline-age", "9" * 10_000 + "w"),
        ("--max-age", "9" * 10_000 + "d"),
        ("--max-age", "private-duration-token-" * 2_000),
        ("--max-baseline-age", " " * 10_000 + "1d"),
    ],
    ids=["65-digits", "large-digits-baseline", "large-digits-age",
         "large-token-age", "large-whitespace"],
)
def test_oversized_duration_is_a_bounded_argparse_error(option: str, value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError) as caught:
        _duration(value, option, f"Fecha={value}" if option == "--max-age" else None)
    message = str(caught.value)
    assert message == f"invalid {option} value: duration exceeds 64 characters (too long)"
    assert len(message) < 120
    assert "99999999" not in message
    assert "private-duration-token" not in message


@pytest.mark.parametrize(
    "argument",
    [
        "--max-baseline-age",
        "--max-age=Fecha",
    ],
)
def test_cli_rejects_very_long_duration_before_opening_csv(
    capsys: pytest.CaptureFixture[str], argument: str
) -> None:
    digits = "9" * 10_000 + "d"
    args = (
        ["missing-source.csv", argument, digits]
        if argument == "--max-baseline-age"
        else ["missing-source.csv", f"{argument}={digits}"]
    )
    with pytest.raises(SystemExit) as caught:
        main(args)
    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"invalid {argument.split('=')[0]} value: duration exceeds 64 characters" in captured.err
    assert "999999999" not in captured.err
    assert "missing-source.csv" not in captured.err


@pytest.mark.parametrize("text", ["0d", "00h", "-1d", "1.5h", "7D", ""])
def test_short_invalid_duration_diagnostics_remain_unchanged(text: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError) as caught:
        _duration(text)
    assert str(caught.value).startswith(f"invalid --max-baseline-age value: {text!r}")
