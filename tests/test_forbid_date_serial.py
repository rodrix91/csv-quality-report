"""Tests for ``--forbid-date-serial NAME`` (issue #308)."""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from csv_quality_report import build_report, evaluate, read_table
from csv_quality_report.checks import CHECK_DATE_SERIAL, CHECK_REQUIRED_COLUMN
from csv_quality_report.cli import main
from csv_quality_report.profile import (
    MAX_DATE_SERIAL,
    DateSerialProfile,
    is_date_serial,
    profile_file,
    serial_date,
)

WriteCsv = Callable[..., Path]
# A delivery log consolidated by hand: the rows pasted from another workbook
# carry the dates' serial numbers (one padded, which counts as its stripped
# value, one with a time of day), "s/d" and an empty cell are missing.
DATA = (
    "Guia;Fecha;Hora entrega;Kilos\n"
    "G1;05/11/2026;05/11/2026 10:15;12,5\n"
    "G2;46331;46331,4270833333;3\n"
    "G3; 46331 ;05/11/2026 16:40;7\n"
    "G4;46336;46336,5;1\n"
    "G5;s/d;;2\n"
    "G6;06/11/2026;06/11/2026 09:00;4\n"
)


def serials(path: Path, name: str = "Fecha", **options: object) -> DateSerialProfile:
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        forbid_date_serial=(name,),
        **options,  # type: ignore[arg-type]
    )
    (found,) = report.date_serials
    return found


# --- what counts as a date serial --------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "46331",
        "1",  # 1900-01-01
        "60",  # Excel's 1900-02-29: counted, though it has no date
        "2958465",  # 9999-12-31, the last date spreadsheets show
        "46336,5",  # a time of day with a decimal comma
        "46336.75",  # and with a decimal point
        "46336,0",
        "45962,99999999999",
    ],
)
def test_date_serials(value: str) -> None:
    assert is_date_serial(value)


@pytest.mark.parametrize(
    "value",
    [
        "0",  # Excel's 1900-01-00
        "2958466",  # after 9999-12-31
        "20261105",  # a compact date, 8 digits
        "046331",  # a leading zero
        "-46331",
        "+46331",
        "46 331",
        "46.331,5",  # two marks: a thousands separator
        "46331,",  # a mark without decimals
        ",5",
        "46331E+0",
        "05/11/2026",
        "2026-11-05",
        "46331 ",  # values are tested stripped
        "٤٦٣٣١",  # Arabic-Indic digits
        "",
    ],
)
def test_other_values(value: str) -> None:
    assert not is_date_serial(value)
    assert serial_date(value) is None


@pytest.mark.parametrize("value", [None, 46331, 46331.5, b"46331"])
def test_values_that_are_not_text(value: object) -> None:
    assert not is_date_serial(value)  # type: ignore[arg-type]
    assert serial_date(value) is None  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", "1900-01-01"),
        ("59", "1900-02-28"),
        ("61", "1900-03-01"),  # after Excel's fictitious 1900-02-29
        ("45962", "2025-11-01"),
        ("46331", "2026-11-05"),
        ("2958465", "9999-12-31"),
        ("46336,5", "2026-11-10 12:00"),
        ("46336.75", "2026-11-10 18:00"),
        ("46336,0", "2026-11-10 00:00"),  # a decimal part always gives a time
        ("46331,4270833333", "2026-11-05 10:15"),  # 10:15 as Excel stores it
        ("46331,427", "2026-11-05 10:14:53"),  # 36892.8 s, rounded to the second
        ("46331,0000057871", "2026-11-05 00:00:01"),  # just over 0.5 s rounds up
        ("46331,000005787", "2026-11-05 00:00"),  # just under 0.5 s rounds down
        ("46331,99999999", "2026-11-06 00:00"),  # rounds up to the next midnight
        ("2958465,99999999", "9999-12-31 23:59:59"),  # but not after 9999-12-31
    ],
)
def test_serial_date(value: str, expected: str) -> None:
    assert serial_date(value) == expected


def test_serial_60_has_no_date() -> None:
    assert is_date_serial("60")
    assert serial_date("60") is None
    assert serial_date("60,5") is None


def test_serial_date_agrees_with_the_1900_date_system() -> None:
    # Every serial from 61 on is that many days after 1899-12-30, and every
    # one before 60 that many after 1899-12-31; check a spread of them.
    for serial in [*range(1, 60), *range(61, 100_000, 997), MAX_DATE_SERIAL]:
        base = date(1899, 12, 31 if serial < 60 else 30)
        assert serial_date(str(serial)) == (base + timedelta(days=serial)).isoformat()


def test_times_agree_with_exact_rounding() -> None:
    # Each second of a day, written with 10 decimals as spreadsheets store
    # it, gives that second back.
    start = datetime(2026, 11, 5)
    for second in range(0, 86400, 37):
        fraction = f"{second / 86400:.10f}"[2:]
        stamp = start + timedelta(seconds=second)
        expected = stamp.strftime("%Y-%m-%d %H:%M" + (":%S" if stamp.second else ""))
        assert serial_date(f"46331,{fraction}") == expected


# --- measuring in the profile ------------------------------------------------


def test_cells_and_examples(write_csv: WriteCsv) -> None:
    found = serials(write_csv(DATA))
    assert found == DateSerialProfile(
        column="Fecha",
        cells=3,
        examples=(("46331", 2), ("46336", 1)),
    )


def test_date_times(write_csv: WriteCsv) -> None:
    found = serials(write_csv(DATA), "Hora entrega")
    assert found == DateSerialProfile(
        column="Hora entrega",
        cells=2,
        examples=(("46331,4270833333", 1), ("46336,5", 1)),
    )


def test_top_limits_the_examples_not_the_count(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    one = serials(path, top_n=1)
    assert (one.cells, one.examples) == (3, (("46331", 2),))
    none = serials(path, top_n=0)
    assert (none.cells, none.examples) == (3, ())


def test_the_profile_agrees_with_is_date_serial(write_csv: WriteCsv) -> None:
    # The profile tests only the values that start with a digit from 1 to 9;
    # it must count exactly the values ``is_date_serial`` accepts, in the
    # order first seen.
    parts = ["", "0", "1", "46331", "9999999", ",", ".", "5", "-", "x", "/"]
    values = list(dict.fromkeys("".join(p) for p in itertools.product(parts, repeat=3)))
    values = [v for v in values if v.strip() == v and v and v != "s/d"]
    path = write_csv("x;y\n" + "".join(f"{v};1\n" for v in values))
    found = serials(path, "x", top_n=len(values))
    expected = tuple((v, 1) for v in values if is_date_serial(v))
    assert len(expected) >= 30
    assert any(not is_date_serial(v) and "1" <= v[:1] <= "9" for v in values)
    assert (found.cells, found.examples) == (len(expected), expected)


def test_ties_keep_the_first_seen_value(write_csv: WriteCsv) -> None:
    path = write_csv("x;y\n46332;1\n46331;1\n")
    assert serials(path, "x").examples == (("46332", 1), ("46331", 1))


def test_a_clean_column(write_csv: WriteCsv) -> None:
    found = serials(write_csv(DATA), "Guia")
    assert found == DateSerialProfile(column="Guia", cells=0)


def test_missing_cells_are_not_checked(write_csv: WriteCsv) -> None:
    # "46331" is listed as a missing-value text, so it is not checked.
    path = write_csv("x;y\n46331;1\n46332;1\n;1\n")
    report = profile_file(path, delimiter=";", na_tokens=("46331",), forbid_date_serial=("x",))
    assert report.date_serials == (
        DateSerialProfile(column="x", cells=1, examples=(("46332", 1),)),
    )


def test_reading_options_do_not_change_the_text_tested(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    assert serials(path, decimal_comma=True) == serials(path)
    assert serials(path, date_order="dmy") == serials(path)
    assert serials(path, number_affixes=("kg",)) == serials(path)


def test_a_value_seen_only_in_a_later_batch_is_found(write_csv: WriteCsv) -> None:
    rows = "".join(
        f"{(date(2026, 1, 1) + timedelta(days=i % 300)):%d/%m/%Y};1\n" for i in range(25_000)
    )
    path = write_csv("Fecha;x\n" + rows + "46331;1\n")
    assert serials(path).examples == (("46331", 1),)
    assert serials(path, max_rows=25_000).cells == 0


def test_unprofiled_and_unknown_columns_are_skipped(write_csv: WriteCsv) -> None:
    report = profile_file(
        write_csv(DATA),
        delimiter=";",
        columns=("Guia",),
        forbid_date_serial=("Fecha", "Nada"),
    )
    assert report.date_serials == ()


def test_build_report_measures_the_same(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    table = read_table(path, delimiter=";")
    built = build_report(table, na_tokens=("s/d",), forbid_date_serial=["Fecha"])
    assert built.date_serials == (serials(path),)


def test_no_names_no_profiles(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv(DATA), delimiter=";").date_serials == ()


# --- evaluate() ----------------------------------------------------------------


def checked(path: Path, **options: object) -> list[tuple[str, str | None, bool, str]]:
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        forbid_date_serial=("Fecha", "Guia"),
        **options,  # type: ignore[arg-type]
    )
    checks = evaluate(report, forbid_date_serial=["Fecha", "Guia", "Fecha"])
    return [(c.check, c.column, c.passed, c.describe()) for c in checks]


def test_evaluate_fails_passes_and_describes(write_csv: WriteCsv) -> None:
    assert checked(write_csv(DATA)) == [
        (
            CHECK_DATE_SERIAL,
            "Fecha",
            False,
            "column 'Fecha' has 3 cells written as spreadsheet date serials (the column was "
            'saved as a number; format it as a date before exporting): "46331" in 2 cells '
            '(probably 2026-11-05), "46336" in 1 cell (probably 2026-11-10)',
        ),
        (CHECK_DATE_SERIAL, "Guia", True, "column 'Guia' has no spreadsheet date serials"),
    ]


def test_evaluate_singular_without_examples_and_serial_60(write_csv: WriteCsv) -> None:
    path = write_csv("Guia;Fecha\nA;60\nB;05/11/2026\n")
    (fecha, _) = checked(path)
    assert fecha[3] == (
        "column 'Fecha' has 1 cell written as spreadsheet date serials (the column was saved "
        'as a number; format it as a date before exporting): "60" in 1 cell (Excel\'s '
        "1900-02-29, a date that does not exist)"
    )
    (fecha, _) = checked(path, top_n=0)
    assert fecha[3] == (
        "column 'Fecha' has 1 cell written as spreadsheet date serials (the column was saved "
        "as a number; format it as a date before exporting)"
    )


def test_evaluate_needs_the_names_in_the_report(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA), delimiter=";")
    with pytest.raises(ValueError, match="'Fecha' has a date serial check but the report"):
        evaluate(report, forbid_date_serial=["Fecha"])


def test_unknown_and_unprofiled_columns(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    report = profile_file(path, delimiter=";")
    checks = evaluate(report, forbid_date_serial=["Fcha"])
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "Fcha", False)
    ]
    narrow = profile_file(path, delimiter=";", columns=("Guia",))
    with pytest.raises(ValueError, match="column 'Fecha' has a per-column check"):
        evaluate(narrow, forbid_date_serial=["Fecha"])


# --- command line --------------------------------------------------------------


def run(write_csv: WriteCsv, *args: str, data: str = DATA) -> int:
    return main([str(write_csv(data)), "--delimiter", "auto", "--na", "s/d", *args])


def test_cli_fails(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(write_csv, "--top", "1", "--forbid-date-serial", "Hora entrega")
    out, err = capsys.readouterr()
    assert code == 8
    assert err == (
        "check failed: column 'Hora entrega' has 2 cells written as spreadsheet date serials "
        "(the column was saved as a number; format it as a date before exporting): "
        '"46331,4270833333" in 1 cell (probably 2026-11-05 10:15)\n'
    )
    assert "- FAIL: column 'Hora entrega' has 2 cells written as spreadsheet date" in out


def test_cli_passes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--forbid-date-serial", "Guia") == 0
    assert "- pass: column 'Guia' has no spreadsheet date serials" in capsys.readouterr().out


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--format", "json", "--forbid-date-serial", "Fecha") == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check == {
        "check": "date_serial",
        "column": "Fecha",
        "limit": 0,
        "value": 3,
        "passed": False,
        "serials": {"46331": 2, "46336": 1},
    }


def test_cli_json_of_a_passing_check(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json", "--forbid-date-serial", "Guia") == 0
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check["serials"] == {}
    assert check["passed"] is True


def test_cli_repeated_name_gives_one_check(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ("--format", "json", "--forbid-date-serial", "Fecha", "--forbid-date-serial", "Fecha")
    assert run(write_csv, *args) == 8
    assert len(json.loads(capsys.readouterr().out)["checks"]) == 1


def test_cli_name_with_commas_and_equals_signs(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a=b,c;d\n46331;1\n")
    assert main([str(path), "--delimiter", ";", "--forbid-date-serial", "a=b,c"]) == 8
    assert "column 'a=b,c' has 1 cell written" in capsys.readouterr().err


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json") == 0
    assert "serial" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--forbid-date-serial", ""], "invalid --forbid-date-serial value: '' (no name)"),
        (["--forbid-date-serial", "  "], "invalid --forbid-date-serial value: '  ' (no name)"),
        (
            ["--columns", "Guia", "--forbid-date-serial", "Fecha"],
            "--forbid-date-serial checks column 'Fecha', which --columns leaves out",
        ),
    ],
)
def test_cli_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(write_csv, *args)
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_cli_unknown_column(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--forbid-date-serial", "Fcha") == 8
    assert "required column 'Fcha' is missing" in capsys.readouterr().err
