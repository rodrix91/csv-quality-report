"""Tests for ``--month-names`` (issue #202)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.compare import load_baseline
from csv_quality_report.inference import DATE_ORDERS, check_month_names, normalize_date
from csv_quality_report.profile import build_report, profile_file, profile_rows
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]
NAMED = "id;fecha\n1;05-oct-2026\n2;12-ene.-2026\n3;3-Setiembre-2026\n4;05-oct-2026\n"

# Every accepted spelling of each month, written out independently of the
# tables in inference.py.
SPELLINGS = {
    1: ("ene", "jan", "enero", "january"),
    2: ("feb", "febrero", "february"),
    3: ("mar", "marzo", "march"),
    4: ("abr", "apr", "abril", "april"),
    5: ("may", "mayo"),
    6: ("jun", "junio", "june"),
    7: ("jul", "julio", "july"),
    8: ("ago", "aug", "agosto", "august"),
    9: ("sep", "sept", "set", "septiembre", "setiembre", "september"),
    10: ("oct", "octubre", "october"),
    11: ("nov", "noviembre", "november"),
    12: ("dic", "dec", "diciembre", "december"),
}
ABBREVIATIONS = {
    *("ene", "jan", "feb", "mar", "abr", "apr", "may", "jun", "jul", "ago", "aug"),
    *("sep", "sept", "set", "oct", "nov", "dic", "dec"),
}


def report_json(path: Path, capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *args]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


@pytest.mark.parametrize(
    ("value", "order", "expected"),
    [
        ("05-oct-2026", "dmy", "2026-10-05"),
        ("5/oct/2026", "dmy", "2026-10-05"),
        ("05.oct.2026", "dmy", "2026-10-05"),
        ("05-OCT-2026", "dmy", "2026-10-05"),
        ("05-Octubre-2026", "dmy", "2026-10-05"),
        ("05-oct.-2026", "dmy", "2026-10-05"),
        ("05/sept./2026", "dmy", "2026-09-05"),
        ("05-May.-2026", "dmy", "2026-05-05"),  # "may" is also an abbreviation
        ("Oct-05-2026", "mdy", "2026-10-05"),
        ("oct./5/2026", "mdy", "2026-10-05"),
        ("2026-oct-05", "ymd", "2026-10-05"),
        ("2026/Ene/5", "ymd", "2026-01-05"),
        # Times follow --date-order, 12-hour clock included.
        ("05-set-2026 9:05", "dmy", "2026-09-05 09:05"),
        ("05-dic-2026T14:30:15", "dmy", "2026-12-05T14:30:15"),
        ("Dec-05-2026 2:30 PM", "mdy", "2026-12-05 14:30"),
        ("05-ago-2026 2:30 p. m.", "dmy", "2026-08-05 14:30"),
        # No calendar check here; inference rejects the result later.
        ("31-feb-2026", "dmy", "2026-02-31"),
        # Left unchanged.
        ("05-ott-2026", "dmy", "05-ott-2026"),  # Italian: not a month here
        ("05-octubre.-2026", "dmy", "05-octubre.-2026"),  # dot after a full name
        ("05.oct..2026", "dmy", "05.oct..2026"),  # dot after a dot separator
        ("05-oct..-2026", "dmy", "05-oct..-2026"),
        ("05-oct/2026", "dmy", "05-oct/2026"),  # mixed separators
        ("05 oct 2026", "dmy", "05 oct 2026"),  # space is not a date separator
        ("05-oct-26", "dmy", "05-oct-26"),  # two-digit year
        ("5 de octubre de 2026", "dmy", "5 de octubre de 2026"),
        ("05-oct-2026", "mdy", "05-oct-2026"),  # the word is not in the month position
        ("05-oct-2026", "ymd", "05-oct-2026"),
        ("Oct-05-2026", "dmy", "Oct-05-2026"),
        ("05-0ct-2026", "dmy", "05-0ct-2026"),  # zero instead of O
        ("05-señ-2026", "dmy", "05-señ-2026"),
        ("05-oct-2026 25:00 PM", "dmy", "05-oct-2026 25:00 PM"),
        # Numeric dates still read as before.
        ("05/10/2026", "dmy", "2026-10-05"),
        ("fecha", "dmy", "fecha"),
        ("", "dmy", ""),
    ],
)
def test_normalize_date_with_month_names(value: str, order: str, expected: str) -> None:
    assert normalize_date(value, order, month_names=True) == expected


@pytest.mark.parametrize("value", ["05-oct-2026", "Oct-05-2026", "2026-oct-05"])
def test_month_names_are_off_by_default(value: str) -> None:
    for order in DATE_ORDERS:
        assert normalize_date(value, order) == value


@pytest.mark.parametrize("month", sorted(SPELLINGS))
def test_every_spelling_of_every_month(month: int) -> None:
    for word in SPELLINGS[month]:
        for written in {word, word.upper(), word.capitalize()}:
            assert normalize_date(f"7-{written}-2026", "dmy", True) == f"2026-{month:02d}-07"
            dotted = normalize_date(f"7-{written}.-2026", "dmy", True)
            if word in ABBREVIATIONS:
                assert dotted == f"2026-{month:02d}-07", written
            else:
                assert dotted == f"7-{written}.-2026", written


def test_no_other_word_is_a_month() -> None:
    # Truncations and extensions of the accepted words are not months.
    known = {word for words in SPELLINGS.values() for word in words}
    near = {w[:n] for w in known for n in range(3, len(w))} | {w + "s" for w in known}
    for word in sorted(near - known):
        assert normalize_date(f"7-{word}-2026", "dmy", True) == f"7-{word}-2026", word


def test_check_month_names() -> None:
    check_month_names(False, None)
    check_month_names(False, "dmy")
    check_month_names(True, "dmy")
    with pytest.raises(ValueError, match="month names need a date order"):
        check_month_names(True, None)


def test_api_needs_a_date_order(write_csv: WriteCsv) -> None:
    path = write_csv(NAMED)
    with pytest.raises(ValueError, match="month names need a date order"):
        profile_file(path, delimiter=";", month_names=True)
    with pytest.raises(ValueError, match="month names need a date order"):
        build_report(read_table(path, delimiter=";"), month_names=True)
    with pytest.raises(ValueError, match="month names need a date order"):
        # Raised before any row is read.
        profile_rows(["d"], iter(()), month_names=True)


def test_named_months_make_a_date_column(write_csv: WriteCsv) -> None:
    path = write_csv(NAMED)
    report = profile_file(path, delimiter=";", date_order="dmy", month_names=True)
    col = report.columns[1]
    assert (col.type, col.min, col.max) == ("date", "2026-01-12", "2026-10-05")
    # Top values and lengths keep the text as written.
    assert col.top_values[0] == ("05-oct-2026", 2)
    assert (col.min_length, col.max_length) == (11, 16)
    assert report.month_names
    same = build_report(read_table(path, delimiter=";"), date_order="dmy", month_names=True)
    assert same == report


def test_without_the_option_the_column_stays_text(write_csv: WriteCsv) -> None:
    path = write_csv(NAMED)
    report = profile_file(path, delimiter=";", date_order="dmy")
    assert (report.columns[1].type, report.month_names) == ("string", False)


def test_unknown_word_is_named_in_the_type_hint(write_csv: WriteCsv) -> None:
    rows = "".join(f"{day:02d}-mar-2026\n" for day in range(1, 10)) + "10-mzo-2026\n"
    col = profile_file(write_csv("fecha\n" + rows), date_order="dmy", month_names=True).columns[0]
    assert col.type == "string"
    assert col.type_hint is not None
    assert (col.type_hint.type, col.type_hint.examples) == ("date", ("10-mzo-2026",))


def test_json_key_only_with_the_option(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(NAMED)
    plain = report_json(path, capsys, "--delimiter", ";", "--date-order", "dmy")
    assert "month_names" not in plain
    named = report_json(path, capsys, "--delimiter", ";", "--date-order", "dmy", "--month-names")
    assert named["month_names"] is True
    keys = list(named)
    assert keys.index("month_names") == keys.index("date_order") + 1
    assert named["columns"][1]["type"] == "date"
    # Apart from the new key and what it reads, the reports are alike.
    del named["month_names"]
    named["columns"][1] = plain["columns"][1]
    assert named == plain


def test_markdown_line(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv(NAMED)
    assert main([str(path), "--delimiter", ";", "--date-order", "dmy"]) == 0
    assert "Month names" not in capsys.readouterr().out
    assert main([str(path), "--delimiter", ";", "--date-order", "dmy", "--month-names"]) == 0
    out = capsys.readouterr().out
    assert "- Date order: day/month/year\n- Month names: Spanish and English" in out
    assert "| fecha | date |" in out


def test_cli_needs_a_date_order(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([str(write_csv(NAMED)), "--delimiter", ";", "--month-names"])
    assert exc.value.code == 2
    assert "--month-names needs --date-order" in capsys.readouterr().err


def test_gates_read_named_dates(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv(NAMED)
    base = [str(path), "--delimiter", ";", "--date-order", "dmy", "--month-names"]
    assert (
        main([*base, "--require-type", "fecha=date", "--range", "fecha=2026-01-01:2026-12-31"]) == 0
    )
    capsys.readouterr()
    assert main([*base, "--range", "fecha=2026-01-01:2026-09-30"]) == 8
    assert "max 2026-10-05" in capsys.readouterr().err


def test_report_serves_as_baseline(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(NAMED)
    report = tmp_path / "report.json"
    args = [str(path), "--delimiter", ";", "--date-order", "dmy", "--month-names"]
    assert main([*args, "--json-output", str(report)]) == 0
    capsys.readouterr()
    assert load_baseline(report)["columns"][1]["type"] == "date"
    assert main([*args, "--baseline", str(report), "--fail-on-schema-change"]) == 0
    capsys.readouterr()
    # Without the option the column reads as text, a schema change.
    assert main([*args[:-1], "--baseline", str(report), "--fail-on-schema-change"]) == 8
    assert "'fecha' date -> string" in capsys.readouterr().err
