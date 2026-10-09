"""Tests for the ``--range`` quality gate (issue #84)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.checks import CHECK_REQUIRED_COLUMN, CHECK_VALUE_RANGE, evaluate
from csv_quality_report.cli import main
from csv_quality_report.profile import profile_file

WriteCsv = Callable[..., Path]
DATA = "peso,cantidad,fecha,nota\n12.5,3,2026-01-05,a\n-1,40,2026-02-10,b\n800,7,2026-03-01,c\n"


def checks(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, list[dict[str, Any]]]:
    code = main([*args, "--format", "json"])
    found: list[dict[str, Any]] = json.loads(capsys.readouterr().out)["checks"]
    return code, found


def test_out_of_range_numbers_fail(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code, found = checks(capsys, str(write_csv(DATA)), "--range", "peso=0:1000")
    assert code == 8
    assert found == [
        {
            "check": "value_range",
            "column": "peso",
            "limit": 1,
            "value": 0,
            "passed": False,
            "expected": "int or float",
            "actual": "float",
            "range": {"min": 0, "max": 1000},
            "observed": {"min": -1.0, "max": 800.0},
        }
    ]


def test_bounds_are_inclusive_and_may_be_open(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA))
    for bounds, passed in [
        ((-1, 800), True),
        ((-1, 799.99), False),
        ((-0.5, 800), False),
        ((-1, None), True),
        ((0, None), False),
        ((None, 800), True),
        ((None, 799), False),
    ]:
        (check,) = evaluate(report, column_ranges={"peso": bounds})
        assert check.passed is passed, bounds


def test_dates(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = str(write_csv(DATA))
    code, found = checks(capsys, path, "--range", "fecha=2026-01-01:2026-02-28")
    assert (code, found[0]["passed"]) == (8, False)
    assert found[0]["range"] == {"min": "2026-01-01", "max": "2026-02-28"}
    assert found[0]["observed"] == {"min": "2026-01-05", "max": "2026-03-01"}
    code, _ = checks(capsys, path, "--range", "fecha=2026-01-05:2026-03-01")
    assert code == 0
    report = profile_file(Path(path))
    (check,) = evaluate(report, column_ranges={"fecha": (None, date(2026, 3, 1))})
    assert check.passed


def test_messages(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    args = [str(write_csv(DATA)), "--range", "peso=0:1000", "--range", "cantidad=1:"]
    assert main([*args, "--range", "fecha=:2026-12-31"]) == 8
    captured = capsys.readouterr()
    assert captured.err == (
        "check failed: column 'peso' has values outside 0..1000 (min -1, max 800)\n"
    )
    assert "- pass: column 'cantidad' is within 1.. (min 3, max 40)\n" in captured.out
    assert "- pass: column 'fecha' is within ..2026-12-31 (min 2026-01-05, max 2026-03-01)\n" in (
        captured.out
    )


def test_observed_values_are_shown_exactly(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("monto\n1234.56\n249140.75\n"))
    (check,) = evaluate(report, column_ranges={"monto": (0, 1000)})
    assert check.describe() == (
        "column 'monto' has values outside 0..1000 (min 1234.56, max 249140.75)"
    )


def test_wrong_column_type_fails_and_says_why(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA))
    note, dates_as_numbers, numbers_as_dates = evaluate(
        report,
        column_ranges={"nota": (0, 1), "fecha": (0, 1), "peso": (date(2026, 1, 1), None)},
    )
    assert (note.passed, note.describe()) == (
        False,
        "column 'nota' is string, a range needs int or float values",
    )
    assert (
        dates_as_numbers.describe() == "column 'fecha' is date, a range needs int or float values"
    )
    assert numbers_as_dates.describe() == "column 'peso' is float, a range needs date values"


def test_type_hint_names_the_stray_values(write_csv: WriteCsv) -> None:
    rows = "".join(f"{i}\n" for i in range(9)) + "12a\n"
    report = profile_file(write_csv("qty\n" + rows))
    (check,) = evaluate(report, column_ranges={"qty": (0, 100)})
    assert check.describe() == (
        "column 'qty' is string, a range needs int or float values (1 value does not fit: \"12a\")"
    )


def test_hint_of_another_kind_is_not_shown(write_csv: WriteCsv) -> None:
    # A mostly-date column checked with numeric bounds: the date hint does not explain it.
    rows = "".join(f"2026-01-0{i}\n" for i in range(1, 10)) + "pendiente\n"
    report = profile_file(write_csv("d\n" + rows))
    (check,) = evaluate(report, column_ranges={"d": (0, 1)})
    assert check.describe() == "column 'd' is string, a range needs int or float values"


def test_datetime_columns_take_date_bounds(write_csv: WriteCsv) -> None:
    # Unsupported until #94, which compares calendar days (tests/test_datetime_range.py).
    report = profile_file(write_csv("t\n2026-01-05T10:00\n"))
    (check,) = evaluate(report, column_ranges={"t": (date(2026, 1, 1), None)})
    assert (check.passed, check.describe()) == (
        True,
        "column 't' is within 2026-01-01.. (min 2026-01-05T10:00, max 2026-01-05T10:00)",
    )


def test_empty_column_passes(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("a,b\n1,\n2,\n"))
    (check,) = evaluate(report, column_ranges={"b": (0, 1)})
    assert (check.check, check.passed) == (CHECK_VALUE_RANGE, True)
    assert check.describe() == "column 'b' has no values to check against 0..1"


def test_unknown_column_is_a_missing_required_column(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA))
    (check,) = evaluate(report, column_ranges={"Peso": (0, 1)})
    assert (check.check, check.column, check.passed) == (CHECK_REQUIRED_COLUMN, "Peso", False)


def test_works_with_reading_options(write_csv: WriteCsv) -> None:
    path = write_csv("saldo;fecha\n(1.234,56);05/10/2026\n2.000,00-;06/10/2026\n10;07/10/2026\n")
    report = profile_file(
        path,
        delimiter=";",
        decimal_comma=True,
        thousands=".",
        date_order="dmy",
        accounting_negatives=True,
    )
    saldo, fecha = evaluate(
        report,
        column_ranges={"saldo": (-1500, None), "fecha": (date(2026, 10, 1), date(2026, 10, 31))},
    )
    assert (saldo.passed, saldo.observed) == (False, (-2000.0, 10.0))
    assert fecha.passed


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("peso", "(use NAME=MIN:MAX; one side may be empty)"),
        ("peso=1", "(use NAME=MIN:MAX; one side may be empty)"),
        ("=0:1", "(use NAME=MIN:MAX; one side may be empty)"),
        ("peso=1:2:3", "(use NAME=MIN:MAX; one side may be empty)"),
        ("peso=:", "(give MIN, MAX or both)"),
        ("peso=a:5", "('a' is not a number, a YYYY-MM-DD date or an ISO 8601 date-time)"),
        ("peso=5:1", "(MIN is greater than MAX)"),
        ("fecha=2026-02-01:2026-01-01", "(MIN is greater than MAX)"),
        ("peso=2026-01-01:5", "(both bounds must be numbers, both dates or both date-times)"),
        ("peso=inf:", "('inf' is not a finite number)"),
        ("peso=:nan", "('nan' is not a finite number)"),
        ("fecha=2026-02-30:", "('2026-02-30' is not a valid date)"),
        ("fecha=20260101:", None),  # a plain number, not a compact date
    ],
)
def test_invalid_values_are_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], value: str, message: str | None
) -> None:
    path = str(write_csv(DATA))
    if message is None:
        assert main([path, "--range", value]) == 8  # numeric bound on a date column
        assert "a range needs int or float values" in capsys.readouterr().err
        return
    with pytest.raises(SystemExit) as excinfo:
        main([path, "--range", value])
    assert excinfo.value.code == 2
    assert f"invalid --range value: {value!r} {message}" in capsys.readouterr().err


def test_names_may_contain_equals_last_range_wins_and_spaces_are_ignored(
    write_csv: WriteCsv,
) -> None:
    path = str(write_csv("a=b\n5\n"))
    assert main([path, "--range", "a=b= 0 : 4 "]) == 8
    assert main([path, "--range", "a=b=0:4", "--range", "a=b=0:5"]) == 0
    assert main([path, "--range", "a=b=-5:5"]) == 0


def test_decimal_and_scientific_bounds(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(DATA))
    assert main([path, "--range", "peso=-1.5:800.0"]) == 0
    capsys.readouterr()
    code, found = checks(capsys, path, "--range", "peso=-0.5:1e3")
    assert (code, found[0]["range"]) == (8, {"min": -0.5, "max": 1000.0})
