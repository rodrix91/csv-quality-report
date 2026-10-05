"""Tests for ``--date-order`` (issue #61)."""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.inference import DATE_ORDERS, check_date_order, normalize_date
from csv_quality_report.profile import build_report, profile_file, profile_rows
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]
DAY_FIRST = "id;fecha\n1;05/10/2026\n2;31/12/2025\n3;1/2/2026\n4;05/10/2026\n"


def report_json(path: Path, capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *args]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


@pytest.mark.parametrize(
    ("value", "order", "expected"),
    [
        ("05/10/2026", "dmy", "2026-10-05"),
        ("05/10/2026", "mdy", "2026-05-10"),
        ("5/1/2026", "dmy", "2026-01-05"),
        ("05-10-2026", "dmy", "2026-10-05"),
        ("05.10.2026", "dmy", "2026-10-05"),
        ("2026/10/5", "ymd", "2026-10-05"),
        ("2026.1.5", "ymd", "2026-01-05"),
        ("2026-10-05", "ymd", "2026-10-05"),
        # Times are kept, with the hour padded and the separator as written.
        ("05/10/2026 9:05", "dmy", "2026-10-05 09:05"),
        ("05/10/2026 14:30:15", "dmy", "2026-10-05 14:30:15"),
        ("10/05/2026T07:00", "mdy", "2026-10-05T07:00"),
        # No calendar check here; inference rejects the result later.
        ("31/02/2026", "dmy", "2026-02-31"),
        # Left unchanged: not a date in the accepted forms.
        ("05/10/26", "dmy", "05/10/26"),  # two-digit year: the century would be a guess
        ("05/10-2026", "dmy", "05/10-2026"),  # mixed separators
        ("005/10/2026", "dmy", "005/10/2026"),
        ("2026/10/05", "dmy", "2026/10/05"),  # year first is not dmy
        ("05/10/2026", "ymd", "05/10/2026"),
        ("2026-10-05", "dmy", "2026-10-05"),  # ISO stays ISO
        ("05/10/2026 9h05", "dmy", "05/10/2026 9h05"),
        ("05/10/2026 9:5", "dmy", "05/10/2026 9:5"),
        ("05/10/2026 09:05 PM", "mdy", "05/10/2026 09:05 PM"),
        ("٠٥/10/2026", "dmy", "٠٥/10/2026"),  # Arabic-Indic digits
        ("fecha", "dmy", "fecha"),
        ("", "dmy", ""),
    ],
)
def test_normalize_date(value: str, order: str, expected: str) -> None:
    assert normalize_date(value, order) == expected


@pytest.mark.parametrize("order", DATE_ORDERS)
def test_normalize_date_agrees_with_strptime(order: str) -> None:
    # Property check against the standard library on random dates and times,
    # with and without zero padding, for every separator.
    rng = random.Random(61)
    formats = {"dmy": "%d{s}%m{s}%Y", "mdy": "%m{s}%d{s}%Y", "ymd": "%Y{s}%m{s}%d"}
    start = datetime(1900, 1, 1)
    for _ in range(500):
        moment = start + timedelta(minutes=rng.randrange(200 * 366 * 24 * 60))
        sep = rng.choice("/-.")
        text = moment.strftime(formats[order].format(s=sep))
        if rng.random() < 0.5:  # drop zero padding of day and month
            parts = text.split(sep)
            text = sep.join(part.lstrip("0") if len(part) == 2 else part for part in parts)
        expected = moment.date().isoformat()
        if rng.random() < 0.5:
            text += moment.strftime(" %H:%M")
            expected += moment.strftime(" %H:%M")
        assert normalize_date(text, order) == expected, text
        assert datetime.fromisoformat(normalize_date(text, order)).date() == moment.date()


def test_check_date_order() -> None:
    check_date_order(None)
    for order in DATE_ORDERS:
        check_date_order(order)
    with pytest.raises(ValueError, match="unsupported date order: 'DMY'"):
        check_date_order("DMY")


def test_day_first_column_becomes_date(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = report_json(write_csv(DAY_FIRST), capsys, "--delimiter", ";", "--date-order", "dmy")
    col = rep["columns"][1]
    assert (col["type"], col["min"], col["max"]) == ("date", "2025-12-31", "2026-10-05")
    # Top values and lengths keep the text as written.
    assert col["top_values"][0] == {"value": "05/10/2026", "count": 2}
    assert (col["min_length"], col["max_length"]) == (8, 10)
    assert rep["date_order"] == "dmy"


def test_without_the_option_nothing_changes(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = report_json(write_csv(DAY_FIRST), capsys, "--delimiter", ";")
    col = rep["columns"][1]
    assert (col["type"], col["min"], col["type_hint"]) == ("string", None, None)
    assert rep["date_order"] is None


def test_the_order_decides_the_reading(write_csv: WriteCsv) -> None:
    path = write_csv("d\n05/10/2026\n12/01/2026\n")
    dmy = profile_file(path, date_order="dmy").columns[0]
    mdy = profile_file(path, date_order="mdy").columns[0]
    assert (dmy.min, dmy.max) == ("2026-01-12", "2026-10-05")
    assert (mdy.min, mdy.max) == ("2026-05-10", "2026-12-01")
    # 13/01/2026 is a date only day first.
    other = write_csv("d\n13/01/2026\n", "other.csv")
    assert profile_file(other, date_order="dmy").columns[0].type == "date"
    assert profile_file(other, date_order="mdy").columns[0].type == "string"


def test_iso_values_mix_with_local_ones(write_csv: WriteCsv) -> None:
    path = write_csv("d\n2026-01-03\n02/01/2026\n2026-01-01\n")
    col = profile_file(path, date_order="dmy").columns[0]
    assert (col.type, col.min, col.max) == ("date", "2026-01-01", "2026-01-03")


def test_date_times_become_datetime(write_csv: WriteCsv) -> None:
    path = write_csv("t\n05/10/2026 9:05\n04/10/2026 23:59:59\n05/10/2026\n")
    col = profile_file(path, date_order="dmy").columns[0]
    assert (col.type, col.min, col.max) == (
        "datetime",
        "2026-10-04 23:59:59",
        "2026-10-05 09:05",
    )


def test_impossible_date_is_named_as_written(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = "".join(f"{day:02d}/03/2026\n" for day in range(1, 10)) + "31/02/2026\n"
    path = write_csv("fecha\n" + rows)
    col = profile_file(path, date_order="dmy").columns[0]
    assert col.type == "string"
    assert col.type_hint is not None
    assert (col.type_hint.type, col.type_hint.examples) == ("date", ("31/02/2026",))
    assert main([str(path), "--date-order", "dmy", "--require-type", "fecha=date"]) == 8
    err = capsys.readouterr().err
    assert 'expected date (1 value does not fit: "31/02/2026")' in err


def test_impossible_time_stays_text(write_csv: WriteCsv) -> None:
    path = write_csv("t\n05/10/2026 24:00\n")
    assert profile_file(path, date_order="dmy").columns[0].type == "string"


def test_numbers_are_not_dates(write_csv: WriteCsv) -> None:
    # Grouped numbers and decimals never look like dates, with both options on.
    path = write_csv("n;d\n1.234,5;05.10.2026\n12.345.678;06.10.2026\n", "both.csv")
    report = profile_file(path, delimiter=";", decimal_comma=True, thousands=".", date_order="dmy")
    number, day = report.columns
    assert (number.type, number.min, number.max) == ("float", 1234.5, 12345678.0)
    assert (day.type, day.min, day.max) == ("date", "2026-10-05", "2026-10-06")


def test_require_type_passes_with_the_option(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(DAY_FIRST)
    args = [str(path), "--delimiter", ";", "--require-type", "fecha=date"]
    assert main(args) == 8
    capsys.readouterr()
    assert main([*args, "--date-order", "dmy"]) == 0


def test_markdown_names_the_order(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv(DAY_FIRST)
    names = {"dmy": "day/month/year", "mdy": "month/day/year", "ymd": "year/month/day"}
    for order, name in names.items():
        assert main([str(path), "--delimiter", ";", "--date-order", order]) == 0
        assert f"\n- Date order: {name}\n" in capsys.readouterr().out
    assert main([str(path), "--delimiter", ";"]) == 0
    assert "Date order" not in capsys.readouterr().out


def test_invalid_order_is_a_usage_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(DAY_FIRST)), "--date-order", "dd/mm/yyyy"])
    assert excinfo.value.code == 2
    assert "invalid choice: 'dd/mm/yyyy'" in capsys.readouterr().err


def test_api_rejects_an_unknown_order_before_reading() -> None:
    def rows() -> Any:
        raise AssertionError("rows must not be read")
        yield  # pragma: no cover - makes this a generator

    with pytest.raises(ValueError, match="unsupported date order"):
        profile_rows(["d"], rows(), date_order="dd/mm")


def test_streaming_and_in_memory_reports_agree(write_csv: WriteCsv) -> None:
    path = write_csv(DAY_FIRST)
    table = read_table(path, delimiter=";")
    streamed = profile_file(path, delimiter=";", date_order="dmy")
    assert streamed == build_report(table, date_order="dmy")
    assert streamed.date_order == "dmy"


def test_unchanged_default_reports(write_csv: WriteCsv) -> None:
    # Reports without the option are identical to passing None explicitly.
    path = write_csv("a,b\n2026-01-01,x\n2026-01-02 10:00,y\n")
    assert profile_file(path) == profile_file(path, date_order=None)
    assert profile_file(path).columns[0].min == "2026-01-01"


def test_min_and_max_dates_are_real_dates() -> None:
    # The ISO rewrite sorts as dates even when the text as written would not.
    values = ["31/01/2026", "01/12/2025", "15/06/2026"]
    result = profile_rows(["d"], [[v] for v in values], date_order="dmy")
    col = result.columns[0]
    assert (col.min, col.max) == (date(2025, 12, 1).isoformat(), date(2026, 6, 15).isoformat())
