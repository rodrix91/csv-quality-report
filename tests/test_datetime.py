"""Tests for the ``datetime`` type and its range (issue #10)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.inference import (
    TYPE_DATE,
    TYPE_DATETIME,
    TYPE_INT,
    TYPE_STRING,
    infer_type,
    parse_datetime,
)

WriteCsv = Callable[..., Path]


def column(path: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *extra]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    found: dict[str, Any] = report["columns"][0]
    return found


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-05T14:30",
        "2026-10-05 14:30",
        "2026-10-05T14:30:59",
        "2026-10-05T14:30:59.5",
        "2026-10-05T14:30:59.123456",
        "2026-10-05T14:30:00Z",
        "2026-10-05T14:30:00+04:00",
        "2026-10-05T14:30:00-0400",
        "2026-10-05T14:30:00-04",
        "2024-02-29T00:00",
    ],
)
def test_accepted_datetime_forms(value: str) -> None:
    assert parse_datetime(value) is not None
    assert infer_type([value]) == TYPE_DATETIME


@pytest.mark.parametrize(
    "value",
    [
        "20261005T143000",  # compact form: accepted by fromisoformat, not here
        "2026-10-05T14",  # hour only
        "2026-10-05T14:30:00,5",  # comma fraction
        "2026-10-05T14:30:00.1234567",  # more than 6 fraction digits
        "2026-10-05t14:30",  # lowercase separator
        "2026-10-05T24:00",  # hour 24
        "2026-02-30T00:00",  # impossible date
        "2026-10-05T14:61",  # impossible minute
        "2026-10-05T14:30+25:00",  # offset of a day or more
        "2026-10-05T14:30 UTC",
        "05/10/2026 14:30",
    ],
)
def test_rejected_datetime_forms(value: str) -> None:
    assert parse_datetime(value) is None
    assert infer_type([value]) == TYPE_STRING


def test_plain_dates_keep_the_date_type() -> None:
    assert infer_type(["2026-10-05", "2026-01-01"]) == TYPE_DATE


def test_dates_mixed_with_datetimes_become_datetime() -> None:
    assert infer_type(["2026-10-05", "2026-10-05T08:00"]) == TYPE_DATETIME


def test_numbers_are_not_mistaken_for_datetimes() -> None:
    assert infer_type(["20261005"]) == TYPE_INT


def test_naive_range_returns_original_text(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("t\n2026-10-05 14:30\n2026-10-05T08:00:00\n2026-10-04\n  \n2026-10-05 14:30\n")
    col = column(path, capsys)
    assert col["type"] == "datetime"
    # The plain date counts as midnight and is the earliest value.
    assert (col["min"], col["max"]) == ("2026-10-04", "2026-10-05 14:30")
    assert col["missing"] == 1


def test_offsets_are_compared_as_instants(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # 10:00-04:00 is 14:00 UTC, later than 12:00Z; 09:00+02:00 is 07:00 UTC.
    path = write_csv("t\n2026-10-05T12:00:00Z\n2026-10-05T10:00:00-04:00\n2026-10-05T09:00+02:00\n")
    col = column(path, capsys)
    assert (col["min"], col["max"]) == ("2026-10-05T09:00+02:00", "2026-10-05T10:00:00-04:00")


def test_mixing_offsets_and_local_times_gives_no_range(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("t\n2026-10-05T12:00:00Z\n2026-10-05T10:00:00\n")
    col = column(path, capsys)
    assert (col["type"], col["min"], col["max"]) == ("datetime", None, None)


def test_equal_instants_keep_the_first_seen_text(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("t\n2026-10-05T10:00:00-04:00\n2026-10-05T14:00:00Z\n")
    col = column(path, capsys)
    assert (col["min"], col["max"]) == ("2026-10-05T10:00:00-04:00", "2026-10-05T10:00:00-04:00")


def test_one_bad_value_makes_the_column_string(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    col = column(write_csv("t\n2026-10-05T10:00\n2026-10-05T25:00\n"), capsys)
    assert (col["type"], col["min"]) == ("string", None)


def test_markdown_shows_the_datetime_range(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("t\n2026-10-05T10:00\n2026-10-05T09:15\n")
    assert main([str(path)]) == 0
    expected = "| t | datetime | 0 | 0.0 | 2 | 2026-10-05T09:15 | 2026-10-05T10:00 |"
    assert expected in capsys.readouterr().out
