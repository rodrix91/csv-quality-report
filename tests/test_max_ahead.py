"""Tests for ``--max-ahead NAME=DURATION`` (issue #327, ADR 0009).

The clock is 2026-11-27T12:00Z throughout; at ``--utc-offset=-04:00`` (La
Paz) that is 08:00 local, and the local day 2026-11-27 began at 04:00Z.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path

import pytest

from csv_quality_report import evaluate
from csv_quality_report.checks import (
    CHECK_MAX_AGE,
    CHECK_MAX_AHEAD,
    CHECK_REQUIRED_COLUMN,
    CheckResult,
)
from csv_quality_report.cli import _column_ahead, main
from csv_quality_report.profile import Report, profile_file

WriteCsv = Callable[..., Path]
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
EPOCH = 1_795_780_800  # 2026-11-27T12:00:00Z
LA_PAZ = timedelta(hours=-4)
MINUTE = 60
HOUR = 3600
DAY = 86_400
DATA = (
    "Venta,Entrega,Despacho,Escaneo,Plan,Remito,Vacía,Mezcla\n"
    "2026-11-20,2026-11-26,2026-11-27 07:30,2026-11-27T10:00-04:00,2026-11-27 10:00,R-1,,"
    "2026-11-27T10:00Z\n"
    "2026-11-27,2026-11-28,2026-11-26 07:00,2026-11-27T09:00Z,2026-11-28,R-2,,2026-11-27 11:00\n"
)


@pytest.fixture
def report(write_csv: WriteCsv) -> Report:
    return profile_file(write_csv(DATA))


def ahead(
    report: Report, name: str, limit: int, offset: timedelta | None = LA_PAZ, now: datetime = NOW
) -> CheckResult:
    (check,) = evaluate(report, column_max_aheads={name: limit}, now=now, utc_offset=offset)
    assert check.check == CHECK_MAX_AHEAD and check.column == name
    return check


def test_the_premises_of_the_file(report: Report) -> None:
    types = {c.name: (c.type, c.max) for c in report.columns}
    assert types["Venta"] == ("date", "2026-11-27")
    assert types["Entrega"] == ("date", "2026-11-28")
    assert types["Despacho"] == ("datetime", "2026-11-27 07:30")
    assert types["Escaneo"] == ("datetime", "2026-11-27T10:00-04:00")  # = 14:00Z, the latest
    assert types["Plan"] == ("datetime", "2026-11-28")  # a date in a datetime column
    assert types["Remito"][0] == "string" and types["Vacía"][0] == "string"
    assert types["Mezcla"] == ("datetime", None)  # offsets mixed: no range


# --- how far ahead -------------------------------------------------------------


def test_a_date_that_has_begun_is_not_ahead(report: Report) -> None:
    # 2026-11-27 began at 2026-11-27T00:00-04:00, 04:00Z: 8 hours before the clock.
    check = ahead(report, "Venta", 0)
    assert (check.passed, check.value, check.limit, check.newest) == (
        True,
        -8 * HOUR,
        0,
        "2026-11-27",
    )
    assert check.describe() == (
        "column 'Venta' is not ahead of the clock: its newest value 2026-11-27 began 8 hours "
        "before it (limit 0 seconds)"
    )


def test_a_date_counts_from_the_start_of_its_day(report: Report) -> None:
    # 2026-11-28 begins at 2026-11-28T04:00Z: 16 hours after the clock.
    check = ahead(report, "Entrega", 0)
    assert (check.passed, check.value) == (False, 16 * HOUR)
    assert check.describe() == (
        "column 'Entrega' is too far ahead: its newest value 2026-11-28 is 16 hours ahead of "
        "the clock (limit 0 seconds)"
    )
    assert ahead(report, "Entrega", 16 * HOUR).passed  # equal to the limit passes
    assert not ahead(report, "Entrega", 16 * HOUR - 1).passed
    assert ahead(report, "Entrega", DAY).describe() == (
        "column 'Entrega' is within the limit: its newest value 2026-11-28 is 16 hours ahead "
        "of the clock (limit 1 day)"
    )


def test_unlike_max_age_a_date_is_not_stretched_to_its_end(report: Report) -> None:
    # The same day is 8 hours old for --max-age (until its end) and 8 hours
    # before the clock for --max-ahead (from its start): each gives it the
    # benefit of the doubt, so neither fails on a date of today.
    late = NOW + timedelta(hours=10)  # 22:00Z, 18:00 local: the day has 6 hours left
    checks = evaluate(
        report,
        column_max_ages={"Venta": DAY},
        column_max_aheads={"Venta": 0},
        now=late,
        utc_offset=LA_PAZ,
    )
    assert [(c.check, c.passed, c.value) for c in checks] == [
        (CHECK_MAX_AGE, True, -6 * HOUR),
        (CHECK_MAX_AHEAD, True, -18 * HOUR),
    ]


def test_naive_times_are_placed_at_the_offset(report: Report) -> None:
    # 07:30-04:00 is 11:30Z: 30 minutes before the clock.
    check = ahead(report, "Despacho", 0)
    assert (check.passed, check.value) == (True, -30 * MINUTE)
    assert check.describe() == (
        "column 'Despacho' is not ahead of the clock: its newest value 2026-11-27 07:30 is "
        "30 minutes before it (limit 0 seconds)"
    )
    assert ahead(report, "Despacho", 0, offset=timedelta(0)).value == -(4 * HOUR + 30 * MINUTE)
    # 07:30-05:00 is 12:30Z: 30 minutes ahead.
    check = ahead(report, "Despacho", 0, offset=timedelta(hours=-5))
    assert (check.passed, check.value) == (False, 30 * MINUTE)
    assert ahead(report, "Despacho", 30 * MINUTE, offset=timedelta(hours=-5)).passed


def test_a_date_in_a_datetime_column_is_midnight(report: Report) -> None:
    # 2026-11-28 at -04:00 is 2026-11-28T04:00Z, as in --range.
    check = ahead(report, "Plan", 0)
    assert (check.passed, check.value, check.newest) == (False, 16 * HOUR, "2026-11-28")
    assert "is too far ahead: its newest value 2026-11-28 is 16 hours ahead" in check.describe()


def test_values_with_an_offset_are_instants(report: Report) -> None:
    for offset in (None, LA_PAZ, timedelta(hours=9)):  # the option does not change them
        check = ahead(report, "Escaneo", HOUR, offset=offset)
        assert (check.passed, check.value) == (False, 2 * HOUR)
    assert ahead(report, "Escaneo", 2 * HOUR, offset=None).passed


def test_naive_values_without_an_offset_fail_and_say_how(report: Report) -> None:
    for name in ("Venta", "Despacho", "Plan"):
        check = ahead(report, name, 52 * 7 * DAY, offset=None)
        assert not check.passed and check.value == 0
        assert check.describe() == (
            f"column '{name}' cannot be checked for values ahead (its values have no UTC "
            "offset; give the offset the export writes its times in, such as "
            "--utc-offset=-04:00)"
        )


def test_fractions_of_a_second_are_dropped(report: Report) -> None:
    # The clock 0.4 seconds before 04:00Z on 28 November: the day begins in
    # 0.4 seconds, which counts as 0 whole seconds and passes a limit of 0.
    now = datetime(2026, 11, 28, 3, 59, 59, 600_000, tzinfo=UTC)
    check = ahead(report, "Entrega", 0, now=now)
    assert (check.passed, check.value) == (True, 0)
    assert check.describe() == (
        "column 'Entrega' is not ahead of the clock: its newest value 2026-11-28 began "
        "0 seconds before it (limit 0 seconds)"
    )
    assert not ahead(report, "Entrega", 0, now=now - timedelta(seconds=1)).passed


def test_now_in_another_offset_is_the_same_instant(report: Report) -> None:
    la_paz_now = NOW.astimezone(timezone(LA_PAZ))
    assert ahead(report, "Entrega", 0, now=la_paz_now).value == 16 * HOUR


# --- columns that cannot be checked ------------------------------------------


def test_an_empty_column_passes(report: Report, write_csv: WriteCsv) -> None:
    # Unlike --max-age (no values, no fresh data), nothing in it is ahead.
    check = ahead(report, "Vacía", 0, offset=None)
    assert (check.passed, check.value, check.newest) == (True, 0, None)
    assert check.describe() == "column 'Vacía' has no values, so none is ahead of the clock"
    report = profile_file(write_csv("id,Fecha\n1,\n2,s/d\n"), na_tokens=("s/d",))
    assert report.columns[1].distinct == 0
    assert ahead(report, "Fecha", 0).passed


def test_a_string_column_names_the_stray_values(write_csv: WriteCsv) -> None:
    days = "".join(f"2026-11-{day:02d}\n" for day in range(1, 10))
    report = profile_file(write_csv("Fecha\n" + days + "s/d?\n"))  # 90% dates: a type hint
    check = ahead(report, "Fecha", 0)
    assert not check.passed and check.newest is None
    assert check.describe() == (
        "column 'Fecha' is string, a time ahead of the clock needs date or datetime values "
        '(1 value does not fit: "s/d?")'
    )


def test_a_string_column_without_a_fitting_hint(report: Report) -> None:
    check = ahead(report, "Remito", DAY)
    assert not check.passed
    assert check.describe() == (
        "column 'Remito' is string, a time ahead of the clock needs date or datetime values"
    )


def test_a_numeric_column_fails(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("Peso\n3\n4\n"))
    check = ahead(report, "Peso", DAY)
    assert not check.passed
    assert check.describe() == (
        "column 'Peso' is int, a time ahead of the clock needs date or datetime values"
    )


def test_a_numeric_hint_is_not_a_date_hint(write_csv: WriteCsv) -> None:
    numbers = "".join(f"{n}\n" for n in range(1, 10))
    report = profile_file(write_csv("Peso\n" + numbers + "x\n"))  # 90% int: an int hint
    assert report.columns[0].type_hint is not None
    assert report.columns[0].type_hint.type == "int"
    check = ahead(report, "Peso", DAY)
    assert check.describe() == (
        "column 'Peso' is string, a time ahead of the clock needs date or datetime values"
    )


def test_a_column_that_mixes_offsets_fails(report: Report) -> None:
    check = ahead(report, "Mezcla", DAY)
    assert not check.passed and check.newest is None
    assert check.describe() == (
        "column 'Mezcla' cannot be checked for values ahead "
        "(it mixes values with and without a UTC offset)"
    )


# --- evaluate() ----------------------------------------------------------------


def test_unknown_columns_fail_as_required(report: Report) -> None:
    checks = evaluate(report, column_max_aheads={"Ventaa": 0}, now=NOW)
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "Ventaa", False)
    ]


class _NoOffset(tzinfo):
    """A tzinfo whose ``utcoffset()`` is None: a datetime with it is not aware."""

    def utcoffset(self, dt: datetime | None) -> None:
        return None

    def dst(self, dt: datetime | None) -> None:
        return None

    def tzname(self, dt: datetime | None) -> None:
        return None


def test_evaluate_needs_an_aware_now(report: Report) -> None:
    for now in (None, NOW.replace(tzinfo=None), NOW.replace(tzinfo=_NoOffset())):
        with pytest.raises(ValueError, match="max_ahead checks need now, an aware datetime"):
            evaluate(report, column_max_aheads={"Venta": 0}, now=now)


@pytest.mark.parametrize("limit", [-1, 1.5, True, "0"])
def test_evaluate_refuses_a_bad_limit(report: Report, limit: object) -> None:
    with pytest.raises(ValueError, match="max ahead for column 'Venta' must be a whole number"):
        evaluate(report, column_max_aheads={"Venta": limit}, now=NOW)  # type: ignore[dict-item]


def test_a_column_left_out_of_the_profile_raises(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA), columns=("Remito",))
    with pytest.raises(ValueError, match="column 'Venta' has a per-column check"):
        evaluate(report, column_max_aheads={"Venta": 0}, now=NOW)


# --- command line --------------------------------------------------------------


def run(
    write_csv: WriteCsv,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    *args: str,
    epoch: int | None = EPOCH,
) -> tuple[int, str, str]:
    if epoch is None:
        monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    else:
        monkeypatch.setenv("SOURCE_DATE_EPOCH", str(epoch))
    code = main([str(write_csv(DATA)), *args])
    out, err = capsys.readouterr()
    return code, out, err


def test_cli_passes_and_fails(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, err = run(
        write_csv, capsys, monkeypatch, "--max-ahead", "Venta=0", "--utc-offset=-04:00"
    )
    assert code == 0 and err == ""
    assert "- pass: column 'Venta' is not ahead of the clock: its newest value 2026-11-27" in out
    code, out, err = run(
        write_csv,
        capsys,
        monkeypatch,
        "--max-ahead",
        "Venta=0",
        "--max-ahead",
        "Entrega=12h",
        "--utc-offset=-04:00",
    )
    assert code == 8
    assert err == (
        "check failed: column 'Entrega' is too far ahead: its newest value 2026-11-28 is "
        "16 hours ahead of the clock (limit 12 hours)\n"
    )


def test_cli_utc_offset_with_max_ahead_alone(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, _, err = run(write_csv, capsys, monkeypatch, "--max-ahead", "Despacho=0")
    assert code == 8 and "--utc-offset=-04:00" in err
    code, _, err = run(
        write_csv, capsys, monkeypatch, "--max-ahead", "Despacho=0", "--utc-offset", "Z"
    )
    assert (code, err) == (0, "")


def test_cli_last_limit_for_a_name_wins(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = run(
        write_csv, capsys, monkeypatch, "--max-ahead", "Escaneo=0", "--max-ahead", "Escaneo=1d"
    )
    assert code == 0 and out.count("column 'Escaneo' is within the limit") == 1


def test_cli_json(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = run(
        write_csv,
        capsys,
        monkeypatch,
        "--format",
        "json",
        "--max-ahead",
        "Entrega=0",
        "--max-ahead",
        "Vacía=0",
        "--utc-offset=-04:00",
    )
    assert code == 8
    assert json.loads(out)["checks"] == [
        {
            "check": "max_ahead",
            "column": "Entrega",
            "limit": 0,
            "value": 16 * HOUR,
            "passed": False,
            "newest": "2026-11-28",
        },
        {
            "check": "max_ahead",
            "column": "Vacía",
            "limit": 0,
            "value": 0,
            "passed": True,
            "newest": None,
        },
    ]


def test_cli_uses_the_real_clock_without_source_date_epoch(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Data from November 2026 is not ahead of any clock after it.
    code, out, err = run(write_csv, capsys, monkeypatch, "--max-ahead", "Escaneo=0", epoch=None)
    assert (code, err) == (0, "")
    assert "column 'Escaneo' is not ahead of the clock" in out


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, plain, _ = run(write_csv, capsys, monkeypatch, "--format", "json", epoch=None)
    assert "max_ahead" not in plain and "newest" not in plain


def test_markdown_lists_the_check(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = run(write_csv, capsys, monkeypatch, "--max-ahead", "Escaneo=1h")
    assert code == 8
    assert (
        "- FAIL: column 'Escaneo' is too far ahead: its newest value 2026-11-27T10:00-04:00 is "
        "2 hours ahead of the clock (limit 1 hour)"
    ) in out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--max-ahead", "Venta"], "invalid --max-ahead value: 'Venta' (use NAME=DURATION"),
        (["--max-ahead", "=0"], "invalid --max-ahead value: '=0' (use NAME=DURATION"),
        (["--max-ahead", "Venta=-1d"], "invalid --max-ahead value: 'Venta=-1d' (use 0 or a"),
        (["--max-ahead", "Venta=1.5d"], "invalid --max-ahead value: 'Venta=1.5d' (use 0 or a"),
        (["--max-ahead", "Venta=7"], "invalid --max-ahead value: 'Venta=7' (use 0 or a"),
        (["--max-ahead", "Venta=0x"], "invalid --max-ahead value: 'Venta=0x' (use 0 or a"),
        (["--max-ahead", "Venta="], "invalid --max-ahead value: 'Venta=' (use 0 or a"),
        (["--max-ahead", "Venta=" + "0" * 65], "duration exceeds 64 characters"),
        (["--max-ahead", "Venta=" + "1" * 65 + "d"], "duration exceeds 64 characters"),
        (["--utc-offset=-04:00"], "--utc-offset needs --max-age or --max-ahead"),
        (["--columns", "Remito", "--max-ahead", "Venta=0"], "--max-ahead checks column 'Venta'"),
    ],
)
def test_cli_usage_errors(
    write_csv: WriteCsv,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    message: str,
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(write_csv, capsys, monkeypatch, *args)
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_cli_bad_source_date_epoch_is_a_usage_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "ayer")
    with pytest.raises(SystemExit) as exc:
        main([str(write_csv(DATA)), "--max-ahead", "Venta=0"])
    assert exc.value.code == 2
    assert "invalid SOURCE_DATE_EPOCH: 'ayer'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("Venta=0", ("Venta", 0)),
        ("Venta=0s", ("Venta", 0)),
        ("Venta=00d", ("Venta", 0)),
        ("Venta= 0 ", ("Venta", 0)),
        ("Venta=5m", ("Venta", 300)),
        ("Venta=1d", ("Venta", DAY)),
        ("Venta=2w", ("Venta", 14 * DAY)),
        ("Fecha=venta=1h", ("Fecha=venta", HOUR)),  # split at the last =
        ("Fecha venta=0", ("Fecha venta", 0)),
    ],
)
def test_parse_durations(text: str, parsed: tuple[str, int]) -> None:
    assert _column_ahead(text) == parsed
