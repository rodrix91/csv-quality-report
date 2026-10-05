"""Tests for the mean of numeric columns (issue #37)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.profile import _mean, build_report, profile_file
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]


def column(path: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *extra]) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)["columns"][0]
    return found


def test_int_mean_is_weighted_by_repeats(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # 1, 1, 1, 9: the distinct-value average would be 5, the real mean is 3.
    assert column(write_csv("n\n1\n1\n1\n9\n"), capsys)["mean"] == 3.0


def test_float_mean_with_missing_and_padding(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    col = column(write_csv("x\n0.5\n\n 1.5\n2.5 \n"), capsys)
    assert (col["type"], col["mean"]) == ("float", 1.5)


def test_mean_is_rounded_to_six_significant_digits(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert column(write_csv("n\n1\n1\n2\n"), capsys)["mean"] == 1.33333


def test_fsum_avoids_naive_summation_loss() -> None:
    values = [1e16, 1.0, -1e16]
    naive = 0.0
    for v in values:  # a plain running total loses the 1.0 next to 1e16
        naive += v
    assert naive / 3 == 0.0
    assert _mean(values, [1, 1, 1]) == 0.333333


def test_decimal_comma_and_na_tokens(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("p\n10,5\nNA\n7,5\n")
    col = column(path, capsys, "--delimiter", ";", "--decimal-comma", "--na", "NA")
    assert (col["type"], col["mean"]) == ("float", 9.0)


def test_non_numeric_columns_have_no_mean(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write_csv("s,d,b\nx,2026-01-01,true\n")), "--format", "json"]) == 0
    cols = json.loads(capsys.readouterr().out)["columns"]
    assert [c["mean"] for c in cols] == [None, None, None]


def test_empty_numeric_column_has_no_mean(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv("n\n\n \n")).columns[0].mean is None


def test_floats_near_the_limit_do_not_overflow() -> None:
    assert _mean([1.5e308, 1.0e308], [3, 1]) == 1.375e308


def test_huge_integers_give_no_mean_instead_of_crashing() -> None:
    huge = 10**400
    assert _mean([huge, 1], [1, 1]) is None


def test_huge_integer_column_from_a_file(write_csv: WriteCsv) -> None:
    col = profile_file(write_csv("n\n" + "9" * 400 + "\n1\n")).columns[0]
    assert (col.type, col.mean) == ("int", None)


def test_negative_values(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert column(write_csv("t\n-4\n2\n-1\n"), capsys)["mean"] == -1.0


def test_streaming_and_in_memory_agree(write_csv: WriteCsv) -> None:
    path = write_csv("a,b\n1,0.25\n2,\n2,0.75\n")
    assert profile_file(path) == build_report(read_table(path))


def test_markdown_shows_the_mean(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    huge = "9" * 400  # a mean of integers this long is not representable as a float
    path = write_csv(f"n,f,t,h\n1,0.5,x,{huge}\n2,0.25,y,{huge}\n4,,z,{huge}\n")
    assert main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "| Min | Max | Mean | Top 3 values |\n" in out
    assert "| n | int | 0 | 0.0 | 3 | 1 | 4 | 2.33333 | " in out
    assert "| f | float | 1 | 33.3 | 2 | 0.25 | 0.5 | 0.375 | " in out
    assert "| t | string | 0 | 0.0 | 3 |  |  |  | " in out
    assert f"| h | int | 0 | 0.0 | 1 | {huge} | {huge} |  | " in out
