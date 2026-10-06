"""Tests for ``--accounting-negatives`` (issue #77)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.inference import accounting_negative
from csv_quality_report.profile import build_report, profile_file
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]
BALANCES = "cuenta;saldo\n1100;1.234,56\n1200;(500,00)\n1300;2.000,00-\n1400;0\n"
SPANISH = ("--delimiter", ";", "--decimal-comma", "--thousands", "dot")
AFFIXES = ("US$", "kg", "$")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("(1.234,56)", "-1.234,56"),
        ("( 1.234,56 )", "-1.234,56"),
        ("( 1.234,56 )", "-1.234,56"),
        ("1.234,56-", "-1.234,56"),
        ("1.234,56 -", "-1.234,56"),
        ("(5)", "-5"),
        ("5-", "-5"),
        # Affixes inside stay for the affix step; a prefix may stand outside.
        ("($ 5)", "-$ 5"),
        ("$ (5)", "-$5"),
        ("$(5)", "-$5"),
        ("US$ (15)", "-US$15"),
        ("(12,5 kg)", "-12,5 kg"),
        ("$ 5-", "-$ 5"),
        # Left as written.
        ("(-5)", "(-5)"),
        ("(+5)", "(+5)"),
        ("-5-", "-5-"),
        ("+5-", "+5-"),
        ("5--", "5--"),
        ("(5)-", "(5)-"),
        ("(5", "(5"),
        ("5)", "5)"),
        ("()", "()"),
        ("-", "-"),
        ("(abc)", "(abc)"),
        ("x-", "x-"),
        ("(1.23,4)", "(1.23,4)"),
        ("2026-10-05", "2026-10-05"),
        ("5", "5"),
        ("-5", "-5"),
        ("", ""),
        ("kg (5)", "-kg5"),  # any affix may come first, as in "kg 5"
        ("(5) kg", "(5) kg"),  # but not after the parentheses
    ],
)
def test_accounting_negative(value: str, expected: str) -> None:
    assert accounting_negative(value, AFFIXES, decimal_comma=True, thousands=".") == expected


def test_without_affixes_symbols_stay() -> None:
    assert accounting_negative("($ 5)") == "($ 5)"
    assert accounting_negative("(5)") == "-5"
    assert accounting_negative("(1,234.5)", thousands=",") == "-1,234.5"
    assert accounting_negative("(1,5)") == "(1,5)"  # not a number without a decimal comma
    assert accounting_negative("(1,5)", decimal_comma=True) == "-1,5"


def report_json(path: Path, capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *args]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


def test_balances_become_numbers(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    rep = report_json(write_csv(BALANCES), capsys, *SPANISH, "--accounting-negatives")
    col = rep["columns"][1]
    assert (col["type"], col["min"], col["max"], col["mean"]) == (
        "float",
        -2000.0,
        1234.56,
        -316.36,
    )
    assert col["top_values"][1] == {"value": "(500,00)", "count": 1}
    assert (col["min_length"], col["max_length"]) == (1, 9)
    assert rep["accounting_negatives"] is True


def test_without_the_option_nothing_changes(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = report_json(write_csv(BALANCES), capsys, *SPANISH)
    col = rep["columns"][1]
    assert (col["type"], col["type_hint"]) == ("string", None)
    assert rep["accounting_negatives"] is False


def test_affixes_of_negatives_are_counted(write_csv: WriteCsv) -> None:
    path = write_csv("a\n$ 10\n$ (2)\n($ 4)\n5-\n")
    col = profile_file(path, number_affixes=("$",), accounting_negatives=True).columns[0]
    assert (col.type, col.min, col.max, col.affixes) == ("int", -5, 10, (("$", 3),))


def test_stray_value_is_named_as_written(write_csv: WriteCsv) -> None:
    rows = "".join(f"({i})\n" for i in range(1, 10)) + "(pendiente)\n"
    col = profile_file(write_csv("saldo\n" + rows), accounting_negatives=True).columns[0]
    assert col.type == "string"
    assert col.type_hint is not None
    assert (col.type_hint.type, col.type_hint.examples) == ("int", ("(pendiente)",))


def test_other_columns_are_not_touched(write_csv: WriteCsv) -> None:
    path = write_csv("nota;fecha\n(ver anexo);2026-10-05\nok-;2026-10-06\n")
    report = profile_file(path, delimiter=";", accounting_negatives=True)
    assert [c.type for c in report.columns] == ["string", "date"]


def test_require_type_passes_with_the_option(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [str(write_csv(BALANCES)), *SPANISH, "--require-type", "saldo=float"]
    assert main(args) == 8
    capsys.readouterr()
    assert main([*args, "--accounting-negatives"]) == 0


def test_markdown_names_the_option(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv(BALANCES)
    assert main([str(path), *SPANISH, "--accounting-negatives"]) == 0
    assert "\n- Accounting negatives: (5) and 5- read as -5\n" in capsys.readouterr().out
    assert main([str(path), *SPANISH]) == 0
    assert "Accounting negatives" not in capsys.readouterr().out


def test_streaming_and_in_memory_reports_agree(write_csv: WriteCsv) -> None:
    path = write_csv(BALANCES)
    options: dict[str, Any] = {
        "decimal_comma": True,
        "thousands": ".",
        "accounting_negatives": True,
    }
    streamed = profile_file(path, delimiter=";", **options)
    assert streamed == build_report(read_table(path, delimiter=";"), **options)
    assert streamed.accounting_negatives
