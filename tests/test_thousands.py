"""Tests for ``--thousands`` (issue #54)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.inference import check_thousands, strip_thousands
from csv_quality_report.profile import build_report, profile_file, profile_rows
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]
SPANISH = "importe;unidades\n1.234,56;1.200\n987,5;35\n12.345.678,9;2.000.000\n"
SP = ("--delimiter", ";", "--decimal-comma", "--thousands", "dot")


def columns(path: Path, capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *args]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


@pytest.mark.parametrize(
    ("value", "sep", "comma", "expected"),
    [
        ("1.234,56", ".", True, "1234,56"),
        ("12.345.678", ".", True, "12345678"),
        ("-1.000", ".", True, "-1000"),
        ("1,234.5", ",", False, "1234.5"),
        ("1,234,567", ",", False, "1234567"),
        ("1 234,5", " ", True, "1234,5"),
        ("1 234 567", " ", False, "1234567"),
        # Not correctly grouped: left unchanged.
        ("1.23", ".", True, "1.23"),
        ("12.34.56", ".", True, "12.34.56"),
        ("1234.567", ".", True, "1234.567"),
        ("1.2345", ".", True, "1.2345"),
        (".234", ".", True, ".234"),
        ("1.234.", ".", True, "1.234."),
        ("1,234,5", ",", False, "1,234,5"),
        ("1.234e5", ".", True, "1.234e5"),
        ("ABC", ".", True, "ABC"),
    ],
)
def test_strip_thousands(value: str, sep: str, comma: bool, expected: str) -> None:
    assert strip_thousands(value, sep, comma) == expected


def test_spanish_export_amounts_and_units(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = columns(write_csv(SPANISH), capsys, *SP)
    importe, unidades = rep["columns"]
    assert (importe["type"], importe["min"], importe["max"]) == ("float", 987.5, 12345678.9)
    assert (unidades["type"], unidades["min"], unidades["max"]) == ("int", 35, 2000000)
    assert importe["mean"] == pytest.approx((1234.56 + 987.5 + 12345678.9) / 3, rel=1e-6)
    # Top values and lengths keep the text as written.
    assert importe["top_values"][0]["value"] == "1.234,56"
    assert importe["max_length"] == len("12.345.678,9")
    assert rep["thousands"] == "."


def test_without_the_option_grouped_numbers_stay_text(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = columns(write_csv(SPANISH), capsys, "--delimiter", ";", "--decimal-comma")
    assert [c["type"] for c in rep["columns"]] == ["string", "string"]
    assert rep["thousands"] is None


def test_english_style_comma_thousands(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = columns(write_csv('amount\n"1,234.5"\n"10,000"\n3\n'), capsys, "--thousands", "comma")
    col = rep["columns"][0]
    assert (col["type"], col["min"], col["max"]) == ("float", 3.0, 10000.0)


def test_badly_grouped_value_makes_a_type_hint(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    data = "n\n" + "".join(f"{i}.000\n" for i in range(1, 30)) + "12.34.56\n"
    col = columns(write_csv(data), capsys, "--decimal-comma", "--thousands", "dot")["columns"][0]
    assert col["type"] == "string"
    assert col["type_hint"]["type"] == "int"
    assert col["type_hint"]["examples"] == ["12.34.56"]  # shown as written


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--thousands", "dot"], "needs a decimal comma"),
        (["--thousands", "comma", "--decimal-comma"], "cannot be the thousands separator"),
        (["--thousands", "apostrophe"], "use dot, comma or space"),
    ],
)
def test_conflicting_or_unknown_separators_are_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv("a\n1\n")), *args])
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err


def test_api_rejects_conflicts_too() -> None:
    with pytest.raises(ValueError, match="needs a decimal comma"):
        profile_rows(["a"], [["1"]], thousands=".")
    with pytest.raises(ValueError, match="unsupported"):
        check_thousands("'", False)


def test_markdown_line(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(write_csv(SPANISH)), *SP]) == 0
    assert "- Thousands separator: dot\n" in capsys.readouterr().out
    assert main([str(write_csv("a\n1\n"))]) == 0
    assert "Thousands" not in capsys.readouterr().out


def test_streaming_and_in_memory_agree(write_csv: WriteCsv) -> None:
    path = write_csv(SPANISH)
    opts: dict[str, Any] = {"decimal_comma": True, "thousands": "."}
    streamed = profile_file(path, delimiter=";", **opts)
    assert streamed == build_report(read_table(path, delimiter=";"), **opts)
