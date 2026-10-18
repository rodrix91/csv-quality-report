"""Tests for ``--max-age NAME=DURATION`` and ``--utc-offset`` (issue #143, ADR 0009)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from csv_quality_report import evaluate
from csv_quality_report.checks import CHECK_MAX_AGE, CHECK_REQUIRED_COLUMN, CheckResult
from csv_quality_report.cli import main
from csv_quality_report.profile import Report, profile_file

WriteCsv = Callable[..., Path]
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
EPOCH = 1_792_324_800  # 2026-10-18T12:00:00Z
LA_PAZ = timedelta(hours=-4)
HOUR = 3600
DAY = 86_400
DATA = (
    "Fecha,Despacho,Escaneo,Remito,Vacía,Mezcla\n"
    "2026-10-10,2026-10-17 18:40,2026-10-17T18:40-04:00,R-1,,2026-10-17T10:00Z\n"
    "2026-10-17,2026-10-16 07:00,2026-10-17T22:00Z,R-2,,2026-10-17 11:00\n"
)


@pytest.fixture
def report(write_csv: WriteCsv) -> Report:
    return profile_file(write_csv(DATA))


def age(
    report: Report, name: str, limit: int, offset: timedelta | None = LA_PAZ, now: datetime = NOW
) -> CheckResult:
    (check,) = evaluate(report, column_max_ages={name: limit}, now=now, utc_offset=offset)
    assert check.check == CHECK_MAX_AGE and check.column == name
    return check


def test_the_premises_of_the_file(report: Report) -> None:
    types = {c.name: (c.type, c.max) for c in report.columns}
    assert types["Fecha"] == ("date", "2026-10-17")
    assert types["Despacho"] == ("datetime", "2026-10-17 18:40")
    assert types["Escaneo"] == ("datetime", "2026-10-17T18:40-04:00")  # = 22:40Z, the latest
    assert types["Remito"][0] == "string" and types["Vacía"][0] == "string"
    assert types["Mezcla"] == ("datetime", None)  # offsets mixed: no range


# --- ages ------------------------------------------------------------------


def test_a_date_counts_until_the_end_of_its_day(report: Report) -> None:
    # 2026-10-17 lasts until 2026-10-18T00:00-04:00, which is 04:00Z: 8 hours before NOW.
    check = age(report, "Fecha", DAY)
    assert (check.passed, check.value, check.limit, check.newest) == (
        True,
        8 * HOUR,
        DAY,
        "2026-10-17",
    )
    assert check.describe() == (
        "column 'Fecha' is fresh: its newest value 2026-10-17 is 8 hours old (limit 1 day)"
    )
    assert age(report, "Fecha", 8 * HOUR).passed  # equal to the limit passes
    assert not age(report, "Fecha", 8 * HOUR - 1).passed


def test_naive_times_are_placed_at_the_offset(report: Report) -> None:
    # 18:40-04:00 is 22:40Z: 13 hours 20 minutes before NOW.
    check = age(report, "Despacho", 10 * HOUR)
    assert (check.passed, check.value) == (False, 13 * HOUR + 20 * 60)
    assert check.describe() == (
        "column 'Despacho' is stale: its newest value 2026-10-17 18:40 is 13 hours 20 minutes "
        "old (limit 10 hours)"
    )
    assert age(report, "Despacho", 10 * HOUR, offset=timedelta(0)).value == 17 * HOUR + 20 * 60
    assert age(report, "Despacho", 10 * HOUR, offset=timedelta(hours=5, minutes=30)).value == (
        22 * HOUR + 50 * 60
    )


def test_values_with_an_offset_are_instants(report: Report) -> None:
    for offset in (None, LA_PAZ, timedelta(hours=9)):  # the option does not change them
        check = age(report, "Escaneo", DAY, offset=offset)
        assert (check.passed, check.value) == (True, 13 * HOUR + 20 * 60)


def test_naive_values_without_an_offset_fail_and_say_how(report: Report) -> None:
    for name in ("Fecha", "Despacho"):
        check = age(report, name, 52 * 7 * DAY, offset=None)
        assert not check.passed and check.value == 0
        assert check.describe() == (
            f"column '{name}' cannot be checked for its age (its values have no UTC offset; "
            "give the offset the export writes its times in, such as --utc-offset=-04:00)"
        )


def test_a_newest_value_ahead_of_the_clock_passes(report: Report) -> None:
    early = datetime(2026, 10, 17, 20, 40, tzinfo=UTC)  # two hours before 22:40Z
    check = age(report, "Escaneo", HOUR, now=early)
    assert (check.passed, check.value) == (True, -2 * HOUR)
    assert check.describe() == (
        "column 'Escaneo' is fresh: its newest value 2026-10-17T18:40-04:00 is 2 hours ahead "
        "of the clock (limit 1 hour)"
    )


def test_fractions_of_a_second_are_dropped(report: Report) -> None:
    now = NOW + timedelta(microseconds=999_999)
    assert age(report, "Fecha", 8 * HOUR, now=now).value == 8 * HOUR


# --- columns that cannot be checked ------------------------------------------


def test_an_empty_column_fails(report: Report, write_csv: WriteCsv) -> None:
    # An empty column has no newest value: no fresh data, whatever its header says.
    check = age(report, "Vacía", DAY)
    assert (check.passed, check.newest) == (False, None)
    assert check.describe() == "column 'Vacía' has no values, so it has no newest value to check"
    report = profile_file(write_csv("id,Fecha\n1,\n2,s/d\n"), na_tokens=("s/d",))
    assert report.columns[1].distinct == 0
    assert "column 'Fecha' has no values" in age(report, "Fecha", DAY).describe()


def test_a_string_column_names_the_stray_values(write_csv: WriteCsv) -> None:
    days = "".join(f"2026-10-{day:02d}\n" for day in range(1, 10))
    report = profile_file(write_csv("Fecha\n" + days + "s/d?\n"))  # 90% dates: a type hint
    check = age(report, "Fecha", DAY)
    assert not check.passed and check.newest is None
    assert check.describe() == (
        "column 'Fecha' is string, an age needs date or datetime values "
        '(1 value does not fit: "s/d?")'
    )


def test_a_string_column_without_a_fitting_hint(report: Report) -> None:
    check = age(report, "Remito", DAY)
    assert check.describe() == "column 'Remito' is string, an age needs date or datetime values"


def test_a_column_that_mixes_offsets_fails(report: Report) -> None:
    check = age(report, "Mezcla", DAY)
    assert not check.passed and check.newest is None
    assert check.describe() == (
        "column 'Mezcla' cannot be checked for its age "
        "(it mixes values with and without a UTC offset)"
    )


def test_a_numeric_column_fails(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("Peso\n3\n4\n"))
    check = age(report, "Peso", DAY)
    assert not check.passed
    assert check.describe() == "column 'Peso' is int, an age needs date or datetime values"


# --- evaluate() ----------------------------------------------------------------


def test_unknown_columns_fail_as_required(report: Report) -> None:
    checks = evaluate(report, column_max_ages={"Fechaa": DAY}, now=NOW)
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "Fechaa", False)
    ]


def test_evaluate_needs_an_aware_now(report: Report) -> None:
    with pytest.raises(ValueError, match="need now, an aware datetime"):
        evaluate(report, column_max_ages={"Fecha": DAY})
    with pytest.raises(ValueError, match="need now, an aware datetime"):
        evaluate(report, column_max_ages={"Fecha": DAY}, now=NOW.replace(tzinfo=None))
    assert evaluate(report, now=None) == []  # no max ages, no clock needed


@pytest.mark.parametrize("limit", [0, -1, 1.5, True])
def test_evaluate_refuses_a_bad_limit(report: Report, limit: object) -> None:
    with pytest.raises(ValueError, match="max age for column 'Fecha' must be a positive whole"):
        evaluate(report, column_max_ages={"Fecha": limit}, now=NOW)  # type: ignore[dict-item]


def test_a_column_left_out_of_the_profile_raises(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA), columns=("Remito",))
    with pytest.raises(ValueError, match="column 'Fecha' has a per-column check"):
        evaluate(report, column_max_ages={"Fecha": DAY}, now=NOW)


def test_now_in_another_offset_is_the_same_instant(report: Report) -> None:
    la_paz_now = NOW.astimezone(timezone(LA_PAZ))
    assert age(report, "Fecha", DAY, now=la_paz_now).value == 8 * HOUR


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
        write_csv, capsys, monkeypatch, "--max-age", "Fecha=1d", "--utc-offset=-04:00"
    )
    assert code == 0 and err == ""
    assert "- pass: column 'Fecha' is fresh: its newest value 2026-10-17 is 8 hours old" in out
    code, out, err = run(
        write_csv,
        capsys,
        monkeypatch,
        "--max-age",
        "Fecha=1d",
        "--max-age",
        "Despacho=10h",
        "--utc-offset",
        "Z",
    )
    assert code == 8
    assert err == (
        "check failed: column 'Despacho' is stale: its newest value 2026-10-17 18:40 is "
        "17 hours 20 minutes old (limit 10 hours)\n"
    )


def test_cli_without_an_offset_fails_the_naive_column(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, _, err = run(
        write_csv, capsys, monkeypatch, "--max-age", "Escaneo=1d", "--max-age", "Fecha=1w"
    )
    assert code == 8
    assert err.count("check failed") == 1 and "--utc-offset=-04:00" in err


def test_cli_last_limit_for_a_name_wins(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = run(
        write_csv, capsys, monkeypatch, "--max-age", "Escaneo=1h", "--max-age", "Escaneo=1d"
    )
    assert code == 0 and out.count("column 'Escaneo' is fresh") == 1


def test_cli_json(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = run(
        write_csv,
        capsys,
        monkeypatch,
        "--format",
        "json",
        "--max-age",
        "Despacho=1d",
        "--utc-offset=-04:00",
    )
    assert code == 0
    assert json.loads(out)["checks"] == [
        {
            "check": "max_age",
            "column": "Despacho",
            "limit": DAY,
            "value": 13 * HOUR + 20 * 60,
            "passed": True,
            "newest": "2026-10-17 18:40",
        }
    ]


def test_cli_uses_the_real_clock_without_source_date_epoch(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Data from October 2026 is older than an hour on any clock after 2026-10-18.
    code, _, err = run(write_csv, capsys, monkeypatch, "--max-age", "Escaneo=1h", epoch=None)
    assert code == 8 and "column 'Escaneo' is stale" in err


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, plain, _ = run(write_csv, capsys, monkeypatch, "--format", "json", epoch=None)
    assert "max_age" not in plain and "newest" not in plain


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--max-age", "Fecha"], "invalid --max-age value: 'Fecha' (use NAME=DURATION"),
        (["--max-age", "=1d"], "invalid --max-age value: '=1d' (use NAME=DURATION"),
        (["--max-age", "Fecha=0d"], "invalid --max-age value: 'Fecha=0d' (use a positive whole"),
        (["--max-age", "Fecha=1.5d"], "invalid --max-age value: 'Fecha=1.5d'"),
        (["--max-age", "Fecha=7"], "invalid --max-age value: 'Fecha=7'"),
        (["--max-age", "Fecha=1d", "--utc-offset=+15:00"], "invalid --utc-offset value: '+15:00'"),
        (["--max-age", "Fecha=1d", "--utc-offset=-04:60"], "invalid --utc-offset value: '-04:60'"),
        (["--max-age", "Fecha=1d", "--utc-offset=4"], "invalid --utc-offset value: '4'"),
        (["--max-age", "Fecha=1d", "--utc-offset=-4:00"], "invalid --utc-offset value: '-4:00'"),
        (["--utc-offset=-04:00"], "--utc-offset needs --max-age"),
        (["--columns", "Remito", "--max-age", "Fecha=1d"], "--max-age checks column 'Fecha'"),
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
        main([str(write_csv(DATA)), "--max-age", "Fecha=1d"])
    assert exc.value.code == 2
    assert "invalid SOURCE_DATE_EPOCH: 'ayer'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("text", "offset"),
    [
        ("Z", timedelta(0)),
        ("z", timedelta(0)),
        ("+00:00", timedelta(0)),
        ("-04:00", LA_PAZ),
        ("+05:30", timedelta(hours=5, minutes=30)),
        ("+14:00", timedelta(hours=14)),
        ("-14:00", timedelta(hours=-14)),
        ("-03:30", timedelta(hours=-3, minutes=-30)),
    ],
)
def test_utc_offsets(text: str, offset: timedelta) -> None:
    from csv_quality_report.cli import _utc_offset

    assert _utc_offset(text) == offset
