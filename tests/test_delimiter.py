"""Tests for ``--delimiter``: semicolon, tab and pipe separated files."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main

WriteCsv = Callable[..., Path]


def run_json(path: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *extra]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


@pytest.mark.parametrize(
    ("flag", "sep"),
    [
        (";", ";"),
        ("semicolon", ";"),
        ("SEMICOLON", ";"),
        ("tab", "\t"),
        ("\\t", "\t"),
        ("\t", "\t"),
        ("|", "|"),
        ("pipe", "|"),
        ("comma", ","),
    ],
)
def test_delimiter_values_and_aliases(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], flag: str, sep: str
) -> None:
    path = write_csv(sep.join(["id", "city"]) + "\n" + sep.join(["1", "La Paz"]) + "\n")
    rep = run_json(path, capsys, "--delimiter", flag)
    assert [c["name"] for c in rep["columns"]] == ["id", "city"]
    assert [c["type"] for c in rep["columns"]] == ["int", "string"]


def test_semicolon_file_with_decimal_commas_keeps_columns_apart(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # Typical export from a Spanish-locale spreadsheet: ';' separates fields and
    # ',' is the decimal mark, so the amount column must stay a single field.
    path = write_csv("sku;amount\nA1;10,5\nB2;7,25\n")
    rep = run_json(path, capsys, "--delimiter", ";")
    assert rep["rows"] == 2
    assert [c["name"] for c in rep["columns"]] == ["sku", "amount"]
    amount = rep["columns"][1]
    assert amount["type"] == "string"  # decimal commas are not parsed as numbers
    assert amount["distinct"] == 2


def test_default_comma_reads_semicolon_file_as_one_column(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a;b\n1;2\n")
    rep = run_json(path, capsys)
    assert [c["name"] for c in rep["columns"]] == ["a;b"]


def test_ragged_rows_detected_with_custom_delimiter(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a;b\n1;2\n3\n")
    assert main([str(path), "--delimiter", ";"]) == 6
    assert "expected 2" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["", ";;", "comma-ish", '"', "\n"])
def test_invalid_delimiter_is_a_usage_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    path = write_csv("a\n1\n")
    with pytest.raises(SystemExit) as excinfo:
        main([str(path), "--delimiter", bad])
    assert excinfo.value.code == 2
    assert "invalid delimiter" in capsys.readouterr().err
