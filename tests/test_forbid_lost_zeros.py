"""Tests for ``--forbid-lost-zeros NAME=WIDTH`` (issue #320)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import build_report, evaluate, read_table
from csv_quality_report.checks import CHECK_LOST_ZEROS, CHECK_REQUIRED_COLUMN
from csv_quality_report.cli import main
from csv_quality_report.profile import (
    MAX_CODE_WIDTH,
    MIN_CODE_WIDTH,
    LostZerosProfile,
    code_width,
    has_lost_zeros,
    profile_file,
)

WriteCsv = Callable[..., Path]
# A Colombian customer export with rows that went through a spreadsheet: the
# DANE municipality codes 05001 and 08001 lost their leading zeros. 11001 and
# 76001 have none to lose; " 05088 " is stripped and keeps them; "s/d" and the
# blank cell are missing; "5001-A", "5.001" and "-5001" are not digit strings,
# and "123456" is longer than the width (both are --pattern's business).
DATA = (
    "Código DANE;Municipio;Vendedor\n"
    "05001;Medellín;0012\n"
    "5001;Medellín;0012\n"
    "5001;Medellín;0007\n"
    "8001;Barranquilla;0031\n"
    "11001;Bogotá;0007\n"
    "76001;Cali;0031\n"
    " 05088 ;Bello;0045\n"
    "s/d;Envigado;0045\n"
    "   ;Itagüí;0045\n"
    "5001-A;Medellín;0012\n"
    "5.001;Medellín;0012\n"
    "-5001;Medellín;0012\n"
    "123456;Rionegro;0012\n"
)


def lost(
    path: Path, width: int = 5, name: str = "Código DANE", **options: object
) -> LostZerosProfile:
    options.setdefault("na_tokens", ("s/d",))
    report = profile_file(
        path,
        delimiter=";",
        forbid_lost_zeros={name: width},
        **options,  # type: ignore[arg-type]
    )
    (found,) = report.lost_zeros
    return found


# --- has_lost_zeros() and code_width() ----------------------------------------


@pytest.mark.parametrize(
    ("value", "width", "expected"),
    [
        ("5001", 5, True),
        ("0", 2, True),
        ("9", 2, True),
        ("0001", 5, True),  # a code padded too short still lost zeros
        ("05001", 5, False),
        ("11001", 5, False),
        ("123456", 5, False),
        ("", 5, False),
        ("5.001", 5, False),
        ("5,001", 5, False),
        ("5001-A", 5, False),
        ("-501", 5, False),
        ("+501", 5, False),
        ("50 1", 5, False),
        ("٥٠٠١", 5, False),  # Arabic-Indic digits, isdigit() but not ASCII
        ("５００１", 5, False),  # fullwidth digits
        ("²", 5, False),  # isdigit() but not a decimal digit
    ],
)
def test_has_lost_zeros(value: str, width: int, expected: bool) -> None:
    assert has_lost_zeros(value, width) is expected


def test_has_lost_zeros_of_a_value_that_is_not_text() -> None:
    assert has_lost_zeros(5001, 5) is False  # type: ignore[arg-type]


@pytest.mark.parametrize("width", [MIN_CODE_WIDTH, 5, MAX_CODE_WIDTH])
def test_code_width_accepts(width: int) -> None:
    assert code_width(width) == width


@pytest.mark.parametrize(
    ("width", "message"),
    [
        (1, "from 2 to 64 digits, got 1"),
        (0, "from 2 to 64 digits, got 0"),
        (-5, "from 2 to 64 digits, got -5"),
        (65, "from 2 to 64 digits, got 65"),
        (True, "must be a whole number, got True"),
        (5.0, "must be a whole number, got 5.0"),
        ("5", "must be a whole number, got '5'"),
    ],
)
def test_code_width_rejects(width: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        code_width(width)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=message):
        has_lost_zeros("1", width)  # type: ignore[arg-type]


# --- measuring in the profile --------------------------------------------------


def test_cells_and_examples(write_csv: WriteCsv) -> None:
    assert lost(write_csv(DATA)) == LostZerosProfile(
        column="Código DANE", width=5, cells=3, examples=(("5001", 2), ("8001", 1))
    )


def test_a_clean_column(write_csv: WriteCsv) -> None:
    assert lost(write_csv(DATA), width=4, name="Vendedor") == LostZerosProfile(
        column="Vendedor", width=4, cells=0
    )


def test_the_width_decides(write_csv: WriteCsv) -> None:
    # With 6 digits, the 5-digit codes count too (and are listed with their cells).
    found = lost(write_csv(DATA), width=6)
    assert found.cells == 7  # 05001, 5001 twice, 8001, 11001, 76001 and 05088
    found = lost(write_csv(DATA), width=4)
    assert found.cells == 0  # no code of the column has fewer than 4 digits


def test_cells_agree_with_has_lost_zeros(write_csv: WriteCsv) -> None:
    table = read_table(write_csv(DATA), delimiter=";")
    cells = [row[0].strip() for row in table.rows]
    for width in range(MIN_CODE_WIDTH, 8):
        expected = sum(has_lost_zeros(cell, width) for cell in cells if cell != "s/d")
        found = lost(write_csv(DATA), width=width)
        assert found.cells == expected, width


def test_missing_cells_are_not_checked(write_csv: WriteCsv) -> None:
    data = "CP;x\ns/d;1\n;2\n  ;3\nN/D;4\n"
    found = lost(write_csv(data), name="CP", na_tokens=("s/d", "N/D"))
    assert found == LostZerosProfile(column="CP", width=5, cells=0)


def test_top_limits_the_examples_not_the_count(write_csv: WriteCsv) -> None:
    found = lost(write_csv(DATA), top_n=1)
    assert found == LostZerosProfile(
        column="Código DANE", width=5, cells=3, examples=(("5001", 2),)
    )
    found = lost(write_csv(DATA), top_n=0)
    assert found == LostZerosProfile(column="Código DANE", width=5, cells=3)


def test_ties_keep_the_first_seen_value(write_csv: WriteCsv) -> None:
    found = lost(write_csv("CP;x\n8001;1\n5001;2\n"), name="CP")
    assert found.examples == (("8001", 1), ("5001", 1))


def test_a_value_seen_only_in_a_later_batch_is_found(write_csv: WriteCsv) -> None:
    data = "CP;x\n" + "05001;1\n" * 5000 + "5001;2\n"
    found = lost(write_csv(data), name="CP")
    assert found == LostZerosProfile(column="CP", width=5, cells=1, examples=(("5001", 1),))


def test_unprofiled_and_unknown_columns_are_skipped(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    report = profile_file(
        path, delimiter=";", columns=("Municipio",), forbid_lost_zeros={"Código DANE": 5}
    )
    assert report.lost_zeros == ()
    report = profile_file(path, delimiter=";", forbid_lost_zeros={"Codigo": 5})
    assert report.lost_zeros == ()


def test_build_report_measures_the_same(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    widths = {"Código DANE": 5, "Vendedor": 4}
    streamed = profile_file(path, delimiter=";", na_tokens=("s/d",), forbid_lost_zeros=widths)
    table = read_table(path, delimiter=";")
    built = build_report(table, na_tokens=("s/d",), forbid_lost_zeros=widths)
    assert built.lost_zeros == streamed.lost_zeros
    assert [found.column for found in built.lost_zeros] == ["Código DANE", "Vendedor"]


def test_widths_are_validated_before_any_row_is_read(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    with pytest.raises(ValueError, match="from 2 to 64 digits, got 1"):
        profile_file(path, delimiter=";", forbid_lost_zeros={"Código DANE": 1})
    table = read_table(path, delimiter=";")
    with pytest.raises(ValueError, match="must be a whole number, got '5'"):
        build_report(table, forbid_lost_zeros={"Código DANE": "5"})  # type: ignore[dict-item]


def test_no_widths_no_profiles(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv(DATA), delimiter=";").lost_zeros == ()


def test_the_rest_of_the_report_is_unchanged(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    plain = profile_file(path, delimiter=";", na_tokens=("s/d",))
    gated = profile_file(
        path, delimiter=";", na_tokens=("s/d",), forbid_lost_zeros={"Código DANE": 5}
    )
    assert plain.columns == gated.columns
    assert gated.lost_zeros != ()


# --- evaluate() ----------------------------------------------------------------


def checked(path: Path, **options: object) -> list[tuple[str, str | None, bool, str]]:
    widths = {"Código DANE": 5, "Vendedor": 4}
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        forbid_lost_zeros=widths,
        **options,  # type: ignore[arg-type]
    )
    checks = evaluate(report, forbid_lost_zeros=widths)
    return [(c.check, c.column, c.passed, c.describe()) for c in checks]


def test_evaluate_fails_passes_and_describes(write_csv: WriteCsv) -> None:
    assert checked(write_csv(DATA)) == [
        (
            CHECK_LOST_ZEROS,
            "Código DANE",
            False,
            "column 'Código DANE' has 3 cells that lost their leading zeros (shorter than 5 "
            "digits, as a spreadsheet saves codes as numbers; export the column as text): "
            '"5001" in 2 cells (probably "05001"), "8001" in 1 cell (probably "08001")',
        ),
        (
            CHECK_LOST_ZEROS,
            "Vendedor",
            True,
            "column 'Vendedor' has no codes shorter than 4 digits",
        ),
    ]


def test_evaluate_singular_and_without_examples(write_csv: WriteCsv) -> None:
    path = write_csv("Código DANE;Vendedor\n5001;0012\n05001;0007\n")
    (dane, _) = checked(path)
    assert dane[3] == (
        "column 'Código DANE' has 1 cell that lost its leading zeros (shorter than 5 digits, "
        'as a spreadsheet saves codes as numbers; export the column as text): "5001" in 1 '
        'cell (probably "05001")'
    )
    (dane, _) = checked(path, top_n=0)
    assert dane[3] == (
        "column 'Código DANE' has 1 cell that lost its leading zeros (shorter than 5 digits, "
        "as a spreadsheet saves codes as numbers; export the column as text)"
    )


def test_evaluate_needs_the_same_widths_in_the_report(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    report = profile_file(path, delimiter=";")
    message = "'Código DANE' has a lost_zeros check but the report was not profiled"
    with pytest.raises(ValueError, match=message):
        evaluate(report, forbid_lost_zeros={"Código DANE": 5})
    report = profile_file(path, delimiter=";", forbid_lost_zeros={"Código DANE": 5})
    with pytest.raises(ValueError, match=message + " with the same width"):
        evaluate(report, forbid_lost_zeros={"Código DANE": 6})
    with pytest.raises(ValueError, match="from 2 to 64 digits, got 99"):
        evaluate(report, forbid_lost_zeros={"Código DANE": 99})


def test_unknown_and_unprofiled_columns(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    report = profile_file(path, delimiter=";")
    checks = evaluate(report, forbid_lost_zeros={"Codigo DANE": 5})
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "Codigo DANE", False)
    ]
    narrow = profile_file(path, delimiter=";", columns=("Municipio",))
    with pytest.raises(ValueError, match="column 'Código DANE' has a per-column check"):
        evaluate(narrow, forbid_lost_zeros={"Código DANE": 5})


# --- command line --------------------------------------------------------------


def run(write_csv: WriteCsv, *args: str, data: str = DATA) -> int:
    return main([str(write_csv(data)), "--delimiter", "auto", "--na", "s/d", *args])


def test_cli_fails(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(write_csv, "--top", "1", "--forbid-lost-zeros", "Código DANE=5")
    out, err = capsys.readouterr()
    assert code == 8
    assert err == (
        "check failed: column 'Código DANE' has 3 cells that lost their leading zeros "
        "(shorter than 5 digits, as a spreadsheet saves codes as numbers; export the column "
        'as text): "5001" in 2 cells (probably "05001")\n'
    )
    assert "- FAIL: column 'Código DANE' has 3 cells that lost their leading zeros" in out


def test_cli_passes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--forbid-lost-zeros", "Vendedor=4") == 0
    out = capsys.readouterr().out
    assert "- pass: column 'Vendedor' has no codes shorter than 4 digits" in out


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--format", "json", "--forbid-lost-zeros", "Código DANE=5") == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check == {
        "check": "lost_zeros",
        "column": "Código DANE",
        "limit": 0,
        "value": 3,
        "passed": False,
        "width": 5,
        "lost_zeros": {"5001": 2, "8001": 1},
    }


def test_cli_json_of_a_passing_check(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json", "--forbid-lost-zeros", "Vendedor=4") == 0
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert (check["width"], check["lost_zeros"], check["passed"]) == (4, {}, True)


def test_cli_the_last_width_for_a_name_wins(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ("--format", "json", "--forbid-lost-zeros", "Código DANE=5")
    assert run(write_csv, *args, "--forbid-lost-zeros", "Código DANE=4") == 0
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert (check["width"], check["value"]) == (4, 0)


def test_cli_width_with_leading_zeros(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json", "--forbid-lost-zeros", "Código DANE=005") == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check["width"] == 5


def test_cli_name_with_commas_and_equals_signs(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a=b,c;d\n12;1\n")
    assert main([str(path), "--delimiter", ";", "--forbid-lost-zeros", "a=b,c=3"]) == 8
    assert "column 'a=b,c' has 1 cell that lost its" in capsys.readouterr().err


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json") == 0
    out = capsys.readouterr().out
    assert "lost_zeros" not in out
    assert '"width"' not in out


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("Código DANE", "invalid --forbid-lost-zeros value: 'Código DANE' (use NAME=WIDTH"),
        ("=5", "invalid --forbid-lost-zeros value: '=5' (use NAME=WIDTH"),
        ("  =5", "invalid --forbid-lost-zeros value: '  =5' (use NAME=WIDTH"),
        ("CP=", "value for 'CP': the code width must be a whole number, got ''"),
        ("CP=+5", "value for 'CP': the code width must be a whole number, got '+5'"),
        ("CP= 5", "value for 'CP': the code width must be a whole number, got ' 5'"),
        ("CP=5.0", "value for 'CP': the code width must be a whole number, got '5.0'"),
        ("CP=٥", "value for 'CP': the code width must be a whole number, got '٥'"),
        ("CP=1", "value for 'CP': the code width must be from 2 to 64 digits, got 1"),
        ("CP=65", "value for 'CP': the code width must be from 2 to 64 digits, got 65"),
        ("CP=00065", "value for 'CP': the code width must be from 2 to 64 digits, got 65"),
        (
            "CP=" + "9" * 21,
            "value for 'CP': the code width must be from 2 to 64 digits, got a number of 21 digits",
        ),
        (
            "CP=" + "0" * 30 + "9" * 20,
            "value for 'CP': the code width must be from 2 to 64 digits, got " + "9" * 20,
        ),
        (
            "CP=" + "9" * 5000,  # more digits than int() converts
            "value for 'CP': the code width must be from 2 to 64 digits, "
            "got a number of 5000 digits",
        ),
    ],
)
def test_cli_invalid_values(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], value: str, message: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(write_csv, "--forbid-lost-zeros", value)
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_cli_column_left_out_by_columns(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(write_csv, "--columns", "Municipio", "--forbid-lost-zeros", "Código DANE=5")
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--forbid-lost-zeros checks column 'Código DANE', which --columns leaves out" in err


def test_cli_unknown_column(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--forbid-lost-zeros", "Codigo DANE=5") == 8
    assert "required column 'Codigo DANE' is missing" in capsys.readouterr().err


def test_only_ascii_digits_count_in_the_profile(write_csv: WriteCsv) -> None:
    # str.isdigit() accepts these, but a spreadsheet never writes them for a code.
    data = "CP;x\n٥٠٠١;1\n５００１;2\n²;3\n5001;4\n"
    assert lost(write_csv(data), name="CP") == LostZerosProfile(
        column="CP", width=5, cells=1, examples=(("5001", 1),)
    )
