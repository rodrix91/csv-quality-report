"""Tests for ``--number-affix`` (issue #73)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.inference import check_number_affixes, split_number_affix
from csv_quality_report.profile import build_report, profile_file, profile_rows
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]
PRICES = "sku;precio\nA;$ 1.234,56\nB;US$ 15\nC;$ 99\nD;-$ 20\n"
SPANISH = ("--delimiter", ";", "--decimal-comma", "--thousands", "dot")
CURRENCY = ("US$", "$")


def report_json(path: Path, capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *args]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("$ 1.234,56", ("1.234,56", "$")),
        ("$1.234,56", ("1.234,56", "$")),
        ("$ 1.234,56", ("1.234,56", "$")),
        ("US$ 15", ("15", "US$")),
        ("-$ 5", ("-5", "$")),
        ("+$ 5", ("+5", "$")),
        ("$ -5", ("-5", "$")),
        ("12,5 kg", ("12,5", "kg")),
        ("-3 kg", ("-3", "kg")),
        ("15 %", ("15", "%")),
        ("15%", ("15", "%")),
        ("Gs. 50.000", ("50.000", "Gs.")),
        # Left as written: no number once the affix is removed.
        ("$", ("$", None)),
        ("$ abc", ("$ abc", None)),
        ("12 kgs", ("12 kgs", None)),
        ("$ 5 kg", ("$ 5 kg", None)),  # two affixes
        ("--$5", ("--$5", None)),
        ("-$ -5", ("-$ -5", None)),
        ("5 $ 6", ("5 $ 6", None)),
        ("1.23,4 kg", ("1.23,4 kg", None)),  # not a grouped number
        ("15", ("15", None)),  # a plain number has no affix
    ],
)
def test_split_number_affix(value: str, expected: tuple[str, str | None]) -> None:
    affixes = ("US$", "Gs.", "kg", "$", "%")
    assert split_number_affix(value, affixes, decimal_comma=True, thousands=".") == expected


def test_the_whole_affix_is_found_in_any_order() -> None:
    # An affix is removed only when a number remains, so "$" can never take
    # just part of "US$": the order of the affixes does not change the result.
    for affixes in (("$", "US$"), ("US$", "$")):
        assert split_number_affix("US$ 15", affixes) == ("15", "US$")
        assert split_number_affix("15 US$", affixes) == ("15", "US$")
    assert split_number_affix("US$15", ("$",)) == ("US$15", None)


def test_rules_follow_decimal_comma_and_thousands() -> None:
    assert split_number_affix("$ 10,5", ("$",)) == ("$ 10,5", None)
    assert split_number_affix("$ 10,5", ("$",), decimal_comma=True) == ("10,5", "$")
    assert split_number_affix("$ 1,234.5", ("$",)) == ("$ 1,234.5", None)
    assert split_number_affix("$ 1,234.5", ("$",), thousands=",") == ("1,234.5", "$")


def test_check_number_affixes() -> None:
    assert check_number_affixes([" $ ", "kg", "$", " %"]) == ("$", "kg", "%")
    for bad, message in [
        (" ", "empty number affix"),
        ("-", "signs and separators only"),
        (".,", "signs and separators only"),
        ("7", "is a number"),
        ("1,5", "is a number"),  # a number with a decimal comma
    ]:
        with pytest.raises(ValueError, match=message):
            check_number_affixes([bad])


def test_prices_become_numbers(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    args = [*SPANISH, "--number-affix", "$", "--number-affix", "US$"]
    rep = report_json(write_csv(PRICES), capsys, *args)
    col = rep["columns"][1]
    assert (col["type"], col["min"], col["max"], col["mean"]) == ("float", -20.0, 1234.56, 332.14)
    assert col["affixes"] == {"$": 3, "US$": 1}
    assert col["top_values"][0] == {"value": "$ 1.234,56", "count": 1}
    assert (col["min_length"], col["max_length"]) == (4, 10)
    assert rep["columns"][0]["affixes"] == {}
    assert rep["number_affixes"] == ["$", "US$"]


def test_without_the_option_nothing_changes(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = report_json(write_csv(PRICES), capsys, *SPANISH)
    assert rep["columns"][1]["type"] == "string"
    assert rep["columns"][1]["affixes"] == {}
    assert rep["number_affixes"] == []


def test_mixed_units_are_reported(write_csv: WriteCsv) -> None:
    path = write_csv("peso\n12 kg\n800 kg\n1200 lb\n5\n")
    col = profile_file(path, number_affixes=("kg", "lb")).columns[0]
    assert (col.type, col.affixes) == ("int", (("kg", 2), ("lb", 1)))


def test_affixes_count_cells_not_distinct_values(write_csv: WriteCsv) -> None:
    path = write_csv("p\n$ 5\n$ 5\n$ 5\n$ 7\n")
    assert profile_file(path, number_affixes=("$",)).columns[0].affixes == (("$", 4),)


def test_stray_value_is_named_as_written(write_csv: WriteCsv) -> None:
    rows = "".join(f"$ {i}\n" for i in range(9)) + "$ consultar\n"
    col = profile_file(write_csv("precio\n" + rows), number_affixes=("$",)).columns[0]
    assert col.type == "string"
    assert col.type_hint is not None
    assert (col.type_hint.type, col.type_hint.examples) == ("int", ("$ consultar",))
    assert col.affixes == (("$", 9),)


def test_percentages_are_not_scaled(write_csv: WriteCsv) -> None:
    col = profile_file(write_csv("d\n15 %\n5%\n"), number_affixes=("%",)).columns[0]
    assert (col.type, col.min, col.max, col.mean) == ("int", 5, 15, 10.0)


def test_require_type_passes_with_the_option(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [str(write_csv(PRICES)), *SPANISH, "--require-type", "precio=float"]
    assert main(args) == 8
    capsys.readouterr()
    assert main([*args, "--number-affix", "$", "--number-affix", "US$"]) == 0


def test_markdown_lists_affixes_per_column(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a|b,c\n$ 1,2 kg\n$ 3,4 lb\n")
    assert (
        main([str(path), "--number-affix", "$", "--number-affix", "kg", "--number-affix", "lb"])
        == 0
    )
    out = capsys.readouterr().out
    assert "\n- Number affixes: a\\|b (`$` 2); c (`kg` 1, `lb` 1)\n" in out
    assert main([str(path)]) == 0
    assert "Number affixes" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("-", "'-' is not a valid number affix"),
        ("7", "'7' is a number, not a number affix"),
        (" ", "empty number affix"),
    ],
)
def test_invalid_affixes_are_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], value: str, message: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(PRICES)), "--number-affix", value])
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err


def test_api_rejects_invalid_affixes_before_reading() -> None:
    def rows() -> Any:
        raise AssertionError("rows must not be read")
        yield  # pragma: no cover - makes this a generator

    with pytest.raises(ValueError, match="is a number"):
        profile_rows(["p"], rows(), number_affixes=("5",))


def test_streaming_and_in_memory_reports_agree(write_csv: WriteCsv) -> None:
    path = write_csv(PRICES)
    options: dict[str, Any] = {"decimal_comma": True, "thousands": ".", "number_affixes": CURRENCY}
    streamed = profile_file(path, delimiter=";", **options)
    assert streamed == build_report(read_table(path, delimiter=";"), **options)
    assert streamed.number_affixes == CURRENCY


def test_given_order_is_kept_in_the_report(write_csv: WriteCsv) -> None:
    # Matching tries longer affixes first, but the report lists them as given.
    report = profile_file(write_csv(PRICES), delimiter=";", number_affixes=("$", "US$", "$"))
    assert report.number_affixes == ("$", "US$")
