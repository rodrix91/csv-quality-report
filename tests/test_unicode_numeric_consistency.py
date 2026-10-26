"""Unicode digit strings must not disagree across the two type inference paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from csv_quality_report.cli import main
from csv_quality_report.inference import infer_type, strip_thousands, value_type


@pytest.mark.parametrize(
    "value",
    [
        "١٢٣",  # Arabic-Indic digits
        "۱۲۳",  # Extended Arabic-Indic digits
        "１２３",  # Fullwidth digits
        "१२३",  # Devanagari digits
        "+١٢",
        "1٢",
        "١.5",
        ".١",
        "١,٢",
        "2e٣",
        "2026-١٠-05",
        "2026-10-05T١٤:٣٠",
    ],
)
@pytest.mark.parametrize("decimal_comma", [False, True])
def test_unicode_digits_are_text_in_both_inference_paths(value: str, decimal_comma: bool) -> None:
    assert infer_type([value], decimal_comma) == "string"
    assert value_type(value, decimal_comma) == "string"
    assert infer_type(["123", value], decimal_comma) == "string"


@pytest.mark.parametrize(
    ("value", "decimal_comma", "expected"),
    [
        ("123", False, "int"),
        ("-123", True, "int"),
        ("12.5", False, "float"),
        ("12,5", True, "float"),
        ("1e2", False, "float"),
        ("2026-10-05", False, "date"),
        ("2026-10-05T14:30", False, "datetime"),
        ("true", False, "bool"),
    ],
)
def test_original_ascii_type_inference_is_unchanged(
    value: str, decimal_comma: bool, expected: str
) -> None:
    assert infer_type([value], decimal_comma) == expected
    assert value_type(value, decimal_comma) == expected


@pytest.mark.parametrize(
    ("value", "sep", "comma"),
    [
        ("١.٢٣٤", ".", True),
        ("１,２３４.５", ",", False),
        ("१ २३४,५", " ", True),
        ("1.٢٣٤,5", ".", True),
    ],
)
def test_thousands_option_preserves_unrecognized_unicode_digit_text(
    value: str, sep: str, comma: bool
) -> None:
    assert strip_thousands(value, sep, comma) == value


def test_cli_keeps_original_unicode_digit_values_as_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "unicode-digits.csv"
    path.write_text("amount\n١٢٣\n٤٥٦\n", encoding="utf-8")
    assert main([str(path), "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    column = report["columns"][0]
    assert column["type"] == "string"
    assert {item["value"] for item in column["top_values"]} == {"١٢٣", "٤٥٦"}
