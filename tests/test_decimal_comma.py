"""Tests for ``--decimal-comma`` (numbers such as ``10,5``)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.inference import TYPE_FLOAT, TYPE_INT, TYPE_STRING, infer_type

WriteCsv = Callable[..., Path]


def run_json(path: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *extra]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["10,5", "-0,25", "3"], TYPE_FLOAT),
        ([",5", "5,", "+1,0"], TYPE_FLOAT),
        (["1,5e3", "2,0E-2"], TYPE_FLOAT),
        (["1", "2", "-3"], TYPE_INT),  # integers are unaffected
        (["1.5", "2,5"], TYPE_STRING),  # '.' is not a decimal mark with the flag
        (["1.234,5"], TYPE_STRING),  # thousands separators are not recognized
        (["1,2,3"], TYPE_STRING),
        (["1,5e999"], TYPE_STRING),  # overflows to infinity
        ([","], TYPE_STRING),
    ],
)
def test_infer_type_with_decimal_comma(values: list[str], expected: str) -> None:
    assert infer_type(values, decimal_comma=True) == expected


def test_default_inference_is_unchanged() -> None:
    assert infer_type(["10,5"]) == TYPE_STRING
    assert infer_type(["10.5"]) == TYPE_FLOAT


def test_semicolon_export_with_decimal_comma(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("sku;price;qty\nA1;10,5;3\nB2;-0,25;7\nC3;;2\n")
    rep = run_json(path, capsys, "--delimiter", ";", "--decimal-comma")
    price = rep["columns"][1]
    assert price["type"] == "float"
    assert (price["min"], price["max"]) == (-0.25, 10.5)
    assert price["missing"] == 1
    # Top values keep the original text, not the parsed number.
    assert price["top_values"][0]["value"] == "10,5"
    assert rep["columns"][2]["type"] == "int"


def test_quoted_decimal_comma_with_comma_delimiter(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv('id,amount\n1,"7,5"\n2,"12,0"\n')
    amount = run_json(path, capsys, "--decimal-comma")["columns"][1]
    assert amount["type"] == "float"
    assert (amount["min"], amount["max"]) == (7.5, 12.0)


def test_without_flag_decimal_commas_stay_strings(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("price\n10,5\n")
    rep = run_json(path, capsys, "--delimiter", ";")
    assert rep["columns"][0]["type"] == "string"
    assert rep["columns"][0]["min"] is None


def test_markdown_output_shows_parsed_range(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("v\n1,5\n2,25\n")
    assert main([str(path), "--delimiter", ";", "--decimal-comma"]) == 0
    out = capsys.readouterr().out
    assert "| v | float | 0 | 0.0 | 2 | 1.5 | 2.25 |" in out
