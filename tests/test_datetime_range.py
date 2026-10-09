"""Tests for ``--range`` on datetime columns and with date-time bounds (issue #94)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.checks import evaluate, range_bounds_problem
from csv_quality_report.cli import main
from csv_quality_report.profile import profile_file

WriteCsv = Callable[..., Path]
# Shipment scans without an offset; a plain date counts as midnight.
SCANS = "guia,escaneo\nA1,2026-10-01T08:15\nA2,2026-10-01 17:40:30\nA3,2026-09-30\n"
# The same kind of column, with offsets: the earliest instant is 2026-10-01T03:00Z.
UTC_SCANS = "escaneo\n2026-10-01T00:00-03:00\n2026-10-01T05:30Z\n2026-10-01T09:00+02:00\n"
UTC_MINUS_3 = timezone(timedelta(hours=-3))


def checks(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, list[dict[str, Any]]]:
    code = main([*args, "--format", "json"])
    found: list[dict[str, Any]] = json.loads(capsys.readouterr().out)["checks"]
    return code, found


def test_datetime_bounds_on_a_datetime_column(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(SCANS))
    code, found = checks(capsys, path, "--range", "escaneo=2026-10-01T00:00:2026-10-01T18:00")
    assert code == 8
    assert found == [
        {
            "check": "value_range",
            "column": "escaneo",
            "limit": 1,
            "value": 0,
            "passed": False,
            "expected": "datetime",
            "actual": "datetime",
            "range": {"min": "2026-10-01T00:00:00", "max": "2026-10-01T18:00:00"},
            "observed": {"min": "2026-09-30", "max": "2026-10-01 17:40:30"},
        }
    ]
    assert main([path, "--range", "escaneo=2026-09-30T00:00:2026-10-01T17:40:30"]) == 0
    captured = capsys.readouterr()
    assert (
        "- pass: column 'escaneo' is within 2026-09-30T00:00:00..2026-10-01T17:40:30 "
        "(min 2026-09-30, max 2026-10-01 17:40:30)\n"
    ) in captured.out


def test_datetime_bounds_are_inclusive_and_may_be_open(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(SCANS))
    earliest, latest = datetime(2026, 9, 30), datetime(2026, 10, 1, 17, 40, 30)
    second = timedelta(seconds=1)
    for bounds, passed in [
        ((earliest, latest), True),
        ((earliest + second, latest), False),  # midnight of the plain date is the min
        ((earliest, latest - second), False),
        ((earliest, None), True),
        ((None, latest), True),
        ((None, latest - second), False),
    ]:
        (check,) = evaluate(report, column_ranges={"escaneo": bounds})
        assert check.passed is passed, bounds


def test_values_with_an_offset_are_compared_as_instants(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(UTC_SCANS))
    first = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)  # 2026-10-01T00:00-03:00
    last = datetime(2026, 10, 1, 7, 0, tzinfo=UTC)  # 2026-10-01T09:00+02:00
    for bounds, passed in [
        ((first, last), True),
        ((first.astimezone(UTC_MINUS_3), last.astimezone(UTC_MINUS_3)), True),
        ((first + timedelta(minutes=1), None), False),
        ((None, last - timedelta(minutes=1)), False),
    ]:
        (check,) = evaluate(report, column_ranges={"escaneo": bounds})
        assert check.passed is passed, bounds
    assert check.observed == ("2026-10-01T00:00-03:00", "2026-10-01T09:00+02:00")


def test_offsets_in_the_option(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = str(write_csv(UTC_SCANS))
    for spec, code in [
        ("2026-10-01T00:00-03:00:2026-10-01T04:00-03:00", 0),  # same instants, written in -03
        ("2026-10-01T03:00Z:2026-10-01T07:00Z", 0),
        ("2026-10-01T03:00+0000:2026-10-01T06:59+00", 8),
        ("2026-10-01T03:00:00.000001+00:00:", 8),
    ]:
        assert main([path, "--range", f"escaneo={spec}"]) == code, spec
    capsys.readouterr()


def test_date_bounds_on_a_datetime_column_compare_calendar_days(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(SCANS))
    # The whole last day is inside: 17:40 on 1 October is within ..2026-10-01.
    code, found = checks(capsys, path, "--range", "escaneo=2026-09-30:2026-10-01")
    assert (code, found[0]["expected"], found[0]["passed"]) == (0, "date", True)
    assert found[0]["range"] == {"min": "2026-09-30", "max": "2026-10-01"}
    report = profile_file(Path(path))
    for bounds, passed in [
        ((date(2026, 10, 1), None), False),
        ((None, date(2026, 9, 30)), False),
        ((date(2026, 9, 30), date(2026, 9, 30)), False),
    ]:
        (check,) = evaluate(report, column_ranges={"escaneo": bounds})
        assert check.passed is passed, bounds


def test_datetime_bounds_on_a_date_column(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("fecha\n2026-10-01\n2026-10-05\n"))
    for bounds, passed in [
        ((datetime(2026, 10, 1), datetime(2026, 10, 5)), True),  # dates are midnight
        ((datetime(2026, 10, 1, 0, 1), None), False),
        ((None, datetime(2026, 10, 4, 23, 59)), False),
    ]:
        (check,) = evaluate(report, column_ranges={"fecha": bounds})
        assert (check.passed, check.expected, check.actual) == (passed, "datetime", "date")


def test_offset_mismatches_fail_and_say_why(write_csv: WriteCsv) -> None:
    aware = profile_file(write_csv(UTC_SCANS, "aware.csv"))
    naive = profile_file(write_csv(SCANS, "naive.csv"))
    utc_bound = datetime(2026, 10, 1, tzinfo=UTC)
    cases = [
        (
            aware,
            (datetime(2026, 10, 1), None),
            "column 'escaneo' cannot be checked against 2026-10-01T00:00:00.. "
            "(its values have a UTC offset and the bounds do not)",
        ),
        (
            naive,
            (None, utc_bound),
            "column 'escaneo' cannot be checked against ..2026-10-01T00:00:00+00:00 "
            "(its values have no UTC offset and the bounds do)",
        ),
        (
            aware,
            (date(2026, 10, 1), date(2026, 10, 1)),
            "column 'escaneo' cannot be checked against 2026-10-01..2026-10-01 "
            "(its values have a UTC offset, so their calendar day depends on the time zone; "
            "use date-times with an offset as bounds)",
        ),
    ]
    for report, bounds, message in cases:
        (check,) = evaluate(report, column_ranges={"escaneo": bounds})
        assert (check.passed, check.describe()) == (False, message)
        assert check.observed == (None, None)


def test_a_column_mixing_offsets_has_no_range(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv("t\n2026-10-01T08:00\n2026-10-01T09:00Z\n"))
    code, found = checks(capsys, path, "--range", "t=2026-10-01T00:00:")
    assert (code, found[0]["observed"]) == (8, {"min": None, "max": None})
    assert main([path, "--range", "t=2026-10-01:"]) == 8
    assert capsys.readouterr().err == (
        "check failed: column 't' cannot be checked against 2026-10-01.. "
        "(it mixes values with and without a UTC offset, so it has no range)\n"
    )


def test_mostly_datetime_columns_name_the_stray_values(write_csv: WriteCsv) -> None:
    rows = "".join(f"2026-10-01T0{i}:00\n" for i in range(9)) + "pendiente\n"
    report = profile_file(write_csv("t\n" + rows))
    (check,) = evaluate(report, column_ranges={"t": (datetime(2026, 10, 1), None)})
    assert check.describe() == (
        "column 't' is string, a range needs datetime values (1 value does not fit: \"pendiente\")"
    )
    (check,) = evaluate(report, column_ranges={"t": (0, 1)})  # a datetime hint, numeric bounds
    assert check.describe() == "column 't' is string, a range needs int or float values"


def test_numeric_columns_reject_datetime_bounds(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("peso\n1\n2\n"))
    (check,) = evaluate(report, column_ranges={"peso": (datetime(2026, 1, 1), None)})
    assert (check.passed, check.describe()) == (
        False,
        "column 'peso' is int, a range needs datetime values",
    )


def test_works_with_date_order(write_csv: WriteCsv) -> None:
    path = write_csv("fecha;guia\n05/10/2026 2:30 p. m.;x\n06/10/2026 09:15;y\n")
    report = profile_file(path, delimiter=";", date_order="dmy")
    (check,) = evaluate(
        report, column_ranges={"fecha": (datetime(2026, 10, 5, 14, 30), datetime(2026, 10, 6))}
    )
    assert (check.passed, check.observed) == (False, ("2026-10-05 14:30", "2026-10-06 09:15"))
    (check,) = evaluate(report, column_ranges={"fecha": (date(2026, 10, 5), date(2026, 10, 6))})
    assert check.passed


@pytest.mark.parametrize(
    ("spec", "low", "high"),
    [
        ("2026-10-01T08:00:2026-10-01T18:00", datetime(2026, 10, 1, 8), datetime(2026, 10, 1, 18)),
        (
            " 2026-10-01 08:00 : 2026-10-01 18:00 ",
            datetime(2026, 10, 1, 8),
            datetime(2026, 10, 1, 18),
        ),
        ("2026-10-01T08:00:", datetime(2026, 10, 1, 8), None),
        (":2026-10-01T18:00:00", None, datetime(2026, 10, 1, 18)),
        ("2026-10-01T08:00:00.5:", datetime(2026, 10, 1, 8, 0, 0, 500000), None),
        (
            "2026-10-01T08:00-03:00:2026-10-01T18:00-0300",
            datetime(2026, 10, 1, 8, tzinfo=UTC_MINUS_3),
            datetime(2026, 10, 1, 18, tzinfo=UTC_MINUS_3),
        ),
        (":2026-10-01T18:00Z", None, datetime(2026, 10, 1, 18, tzinfo=UTC)),
    ],
)
def test_the_range_splits_at_the_colon_between_bounds(
    write_csv: WriteCsv,
    capsys: pytest.CaptureFixture[str],
    spec: str,
    low: datetime | None,
    high: datetime | None,
) -> None:
    path = str(write_csv("t\n2026-10-01T09:00\n"))
    _, found = checks(capsys, path, "--range", f"t={spec}")
    expected = {
        "min": None if low is None else low.isoformat(),
        "max": None if high is None else high.isoformat(),
    }
    assert found[0]["range"] == expected


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("t=2026-10-01T08:00:30", "(use NAME=MIN:MAX; one side may be empty)"),  # seconds
        ("t=2026-10-01T08:00:5", "(both bounds must be numbers, both dates or both date-times)"),
        ("t=2026-10-01T08:00", "(use NAME=MIN:MAX; one side may be empty)"),
        ("t=2026-10-01:2026-10-01T18:00", "(both bounds must be numbers, both dates or both "),
        ("t=0:2026-10-01T18:00", "(both bounds must be numbers, both dates or both date-times)"),
        ("t=2026-10-01T08:00:2026-10-01T18:00Z", "(both date-times must have a UTC offset, or "),
        ("t=2026-10-01T18:00:2026-10-01T08:00", "(MIN is greater than MAX)"),
        ("t=2026-10-01T08:00Z:2026-10-01T07:00-03:00", None),  # 08:00Z is before 10:00Z
        ("t=2026-10-01T09:00Z:2026-10-01T05:00-03:00", "(MIN is greater than MAX)"),
        ("t=2026-02-30T08:00:", "('2026-02-30T08:00' is not a valid date-time)"),
        ("t=2026-10-01T24:00:", "('2026-10-01T24:00' is not a valid date-time)"),
        ("t=2026-10-01T08:00:00.1234567:", "('2026-10-01T08:00:00.1234567' is not a valid "),
        ("t=2026-10-01T08:00+25:00:", "('2026-10-01T08:00+25:00' is not a valid date-time)"),
        ("t=2026-10-01T8:00:", "(use NAME=MIN:MAX; one side may be empty)"),
    ],
)
def test_invalid_date_time_bounds_are_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], value: str, message: str | None
) -> None:
    path = str(write_csv("t\n2026-10-01T09:00Z\n"))
    if message is None:
        assert main([path, "--range", value]) == 0  # 09:00Z is within 08:00Z..10:00Z
        return
    with pytest.raises(SystemExit) as excinfo:
        main([path, "--range", value])
    assert excinfo.value.code == 2
    assert f"invalid --range value: {value!r} {message}" in capsys.readouterr().err


def test_bounds_problems() -> None:
    utc = UTC
    assert range_bounds_problem(None, None) is None
    assert range_bounds_problem(1, None) is None
    assert range_bounds_problem(1, 2.5) is None
    assert range_bounds_problem(date(2026, 1, 1), date(2026, 1, 2)) is None
    assert range_bounds_problem(datetime(2026, 1, 1), datetime(2026, 1, 2)) is None
    assert range_bounds_problem(datetime(2026, 1, 1, tzinfo=utc), datetime(2026, 1, 2)) == (
        "both date-times must have a UTC offset, or neither"
    )
    assert range_bounds_problem(date(2026, 1, 1), datetime(2026, 1, 2)) == (
        "both bounds must be numbers, both dates or both date-times"
    )
    assert range_bounds_problem(0, date(2026, 1, 2)) == (
        "both bounds must be numbers, both dates or both date-times"
    )


def test_the_api_rejects_bounds_that_cannot_form_a_range(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(SCANS))
    with pytest.raises(ValueError, match="invalid range for column 'escaneo': both bounds"):
        evaluate(report, column_ranges={"escaneo": (date(2026, 1, 1), datetime(2026, 1, 2))})
