"""Tests for ``--forbid-scientific NAME`` (issue #303)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import build_report, evaluate, read_table
from csv_quality_report.checks import CHECK_REQUIRED_COLUMN, CHECK_SCIENTIFIC_NOTATION
from csv_quality_report.cli import main
from csv_quality_report.profile import ScientificProfile, is_scientific, profile_file

WriteCsv = Callable[..., Path]
# A product list saved again from a spreadsheet: two GTINs and one tracking
# number became scientific notation (one padded, which counts as its stripped
# value), "s/d" and an empty cell are missing.
DATA = (
    "Codigo;GTIN;Guia\n"
    "A1;7790001234567;123456789012\n"
    "A2;7,79E+12;1,23457E+11\n"
    "A3;7790001234574; 1,23457E+11 \n"
    "A4;7,79000123457E+12;987654321098\n"
    "A5;s/d;\n"
    "A6;7,79E+12;555000111222\n"
)


def scientific(path: Path, name: str = "GTIN", **options: object) -> ScientificProfile:
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        forbid_scientific=(name,),
        **options,  # type: ignore[arg-type]
    )
    (found,) = report.scientific
    return found


# --- what counts as scientific notation ----------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "7,79E+12",  # Excel with a decimal comma
        "7.79E+12",  # Excel with a decimal point
        "1,23457E+11",
        "1E+12",  # a one-digit mantissa has no decimal mark
        "7,79000123457E+12",
        "1.5e-05",  # lower-case, as pandas and Python write it
        "-2,5E+03",
        "+2,5E+03",
        "7.E+12",  # a mark with no decimals
        ",5E+3",  # no integer part
        ".5e+3",
        "1E+0",
    ],
)
def test_scientific_values(value: str) -> None:
    assert is_scientific(value)


@pytest.mark.parametrize(
    "value",
    [
        "7790001234567",
        "12E45",  # a product code: the exponent has no sign
        "3E10",
        "1,5",
        "E+12",  # no mantissa
        "7,79E+",  # no exponent
        "7,79E+1,2",
        "7,79 E+12",  # spaces inside
        " 7,79E+12",  # surrounding whitespace is stripped before the test
        "7,79E++12",
        "7,79F+12",
        "1.234,5E+3",  # thousands separators are not part of the notation
        ".E+3",  # a mark alone is not a mantissa
        "٧,٧٩E+١٢",  # non-ASCII digits
        "7,79E+12\n",  # fullmatch: a trailing newline does not count
        "",
        "ABC-7,79E+12",
    ],
)
def test_other_values(value: str) -> None:
    assert not is_scientific(value)


@pytest.mark.parametrize("value", [None, 7.79e12, 1, b"7,79E+12"])
def test_values_that_are_not_text(value: object) -> None:
    assert not is_scientific(value)  # type: ignore[arg-type]


# --- measuring in the profile ------------------------------------------------


def test_cells_and_examples(write_csv: WriteCsv) -> None:
    found = scientific(write_csv(DATA))
    assert found == ScientificProfile(
        column="GTIN",
        cells=3,
        examples=(("7,79E+12", 2), ("7,79000123457E+12", 1)),
    )


def test_stripped_values_are_counted_together(write_csv: WriteCsv) -> None:
    found = scientific(write_csv(DATA), "Guia")
    assert found == ScientificProfile(column="Guia", cells=2, examples=(("1,23457E+11", 2),))


def test_top_limits_the_examples_not_the_count(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    one = scientific(path, top_n=1)
    assert (one.cells, one.examples) == (3, (("7,79E+12", 2),))
    none = scientific(path, top_n=0)
    assert (none.cells, none.examples) == (3, ())


def test_lower_and_upper_case_exponents_are_found(write_csv: WriteCsv) -> None:
    path = write_csv("x;y\n1.5e-05;1\n2E+5;1\n2E+5;1\n12E45;1\n")
    found = scientific(path, "x")
    assert (found.cells, found.examples) == (3, (("2E+5", 2), ("1.5e-05", 1)))


def test_the_profile_agrees_with_is_scientific(write_csv: WriteCsv) -> None:
    # The profile tests only the values that contain an E; it must count
    # exactly the values ``is_scientific`` accepts, in the order first seen.
    import itertools

    parts = ["", "1", "7,79", ".5", "-", "E", "e", "+", "12", "x", ","]
    values = list(dict.fromkeys("".join(p) for p in itertools.product(parts, repeat=4)))
    values = [v for v in values if v.strip() == v and v and v != "s/d"]
    path = write_csv("x;y\n" + "".join(f"{v};1\n" for v in values))
    found = scientific(path, "x", top_n=len(values))
    expected = tuple((v, 1) for v in values if is_scientific(v))
    assert len(expected) >= 30
    assert (found.cells, found.examples) == (len(expected), expected)


def test_ties_keep_the_first_seen_value(write_csv: WriteCsv) -> None:
    path = write_csv("x;y\n2E+5;1\n1E+5;1\n")
    assert scientific(path, "x").examples == (("2E+5", 1), ("1E+5", 1))


def test_a_clean_column(write_csv: WriteCsv) -> None:
    found = scientific(write_csv(DATA), "Codigo")
    assert found == ScientificProfile(column="Codigo", cells=0)


def test_missing_cells_are_not_checked(write_csv: WriteCsv) -> None:
    # "1E+3" is listed as a missing-value text, so it is not checked.
    path = write_csv("x;y\n1E+3;1\n2E+3;1\n;1\n")
    report = profile_file(path, delimiter=";", na_tokens=("1E+3",), forbid_scientific=("x",))
    assert report.scientific == (ScientificProfile(column="x", cells=1, examples=(("2E+3", 1),)),)


def test_reading_options_do_not_change_the_text_tested(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    assert scientific(path, decimal_comma=True) == scientific(path)
    assert scientific(path, number_affixes=("kg",)) == scientific(path)


def test_a_value_seen_only_in_a_later_batch_is_found(write_csv: WriteCsv) -> None:
    rows = "".join(f"{7790001234567 + i};1\n" for i in range(25_000))
    path = write_csv("GTIN;x\n" + rows + "7,79E+12;1\n")
    assert scientific(path).examples == (("7,79E+12", 1),)
    assert scientific(path, max_rows=25_000).cells == 0


def test_unprofiled_and_unknown_columns_are_skipped(write_csv: WriteCsv) -> None:
    report = profile_file(
        write_csv(DATA),
        delimiter=";",
        columns=("Codigo",),
        forbid_scientific=("GTIN", "Nada"),
    )
    assert report.scientific == ()


def test_build_report_measures_the_same(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    table = read_table(path, delimiter=";")
    built = build_report(table, na_tokens=("s/d",), forbid_scientific=["GTIN"])
    assert built.scientific == (scientific(path),)


def test_no_names_no_profiles(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv(DATA), delimiter=";").scientific == ()


# --- evaluate() ----------------------------------------------------------------


def checked(path: Path, **options: object) -> list[tuple[str, str | None, bool, str]]:
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        forbid_scientific=("GTIN", "Codigo"),
        **options,  # type: ignore[arg-type]
    )
    checks = evaluate(report, forbid_scientific=["GTIN", "Codigo", "GTIN"])
    return [(c.check, c.column, c.passed, c.describe()) for c in checks]


def test_evaluate_fails_passes_and_describes(write_csv: WriteCsv) -> None:
    assert checked(write_csv(DATA)) == [
        (
            CHECK_SCIENTIFIC_NOTATION,
            "GTIN",
            False,
            "column 'GTIN' has 3 cells written in scientific notation, as spreadsheets save "
            "long numbers (only the digits of the mantissa are kept; export the column as "
            'text): "7,79E+12" in 2 cells, "7,79000123457E+12" in 1 cell',
        ),
        (
            CHECK_SCIENTIFIC_NOTATION,
            "Codigo",
            True,
            "column 'Codigo' has no values in scientific notation",
        ),
    ]


def test_evaluate_singular_and_without_examples(write_csv: WriteCsv) -> None:
    path = write_csv("Codigo;GTIN\nA;7,79E+12\nB;7790001234567\n")
    (gtin, _) = checked(path)
    assert gtin[3] == (
        "column 'GTIN' has 1 cell written in scientific notation, as spreadsheets save long "
        "numbers (only the digits of the mantissa are kept; export the column as text): "
        '"7,79E+12" in 1 cell'
    )
    (gtin, _) = checked(path, top_n=0)
    assert gtin[3] == (
        "column 'GTIN' has 1 cell written in scientific notation, as spreadsheets save long "
        "numbers (only the digits of the mantissa are kept; export the column as text)"
    )


def test_evaluate_needs_the_names_in_the_report(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA), delimiter=";")
    with pytest.raises(ValueError, match="'GTIN' has a scientific_notation check but the"):
        evaluate(report, forbid_scientific=["GTIN"])


def test_unknown_and_unprofiled_columns(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    report = profile_file(path, delimiter=";")
    checks = evaluate(report, forbid_scientific=["GTN"])
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "GTN", False)
    ]
    narrow = profile_file(path, delimiter=";", columns=("Codigo",))
    with pytest.raises(ValueError, match="column 'GTIN' has a per-column check"):
        evaluate(narrow, forbid_scientific=["GTIN"])


# --- command line --------------------------------------------------------------


def run(write_csv: WriteCsv, *args: str, data: str = DATA) -> int:
    return main([str(write_csv(data)), "--delimiter", "auto", "--na", "s/d", *args])


def test_cli_fails(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(write_csv, "--top", "1", "--forbid-scientific", "Guia")
    out, err = capsys.readouterr()
    assert code == 8
    assert err == (
        "check failed: column 'Guia' has 2 cells written in scientific notation, as "
        "spreadsheets save long numbers (only the digits of the mantissa are kept; export "
        'the column as text): "1,23457E+11" in 2 cells\n'
    )
    assert "- FAIL: column 'Guia' has 2 cells written in scientific notation" in out


def test_cli_passes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--forbid-scientific", "Codigo") == 0
    assert "- pass: column 'Codigo' has no values in scientific notation" in capsys.readouterr().out


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--format", "json", "--forbid-scientific", "GTIN") == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check == {
        "check": "scientific_notation",
        "column": "GTIN",
        "limit": 0,
        "value": 3,
        "passed": False,
        "scientific": {"7,79E+12": 2, "7,79000123457E+12": 1},
    }


def test_cli_json_of_a_passing_check(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json", "--forbid-scientific", "Codigo") == 0
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check["scientific"] == {}
    assert check["passed"] is True


def test_cli_repeated_name_gives_one_check(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ("--format", "json", "--forbid-scientific", "GTIN", "--forbid-scientific", "GTIN")
    assert run(write_csv, *args) == 8
    assert len(json.loads(capsys.readouterr().out)["checks"]) == 1


def test_cli_name_with_commas_and_equals_signs(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a=b,c;d\n1E+5;1\n")
    assert main([str(path), "--delimiter", ";", "--forbid-scientific", "a=b,c"]) == 8
    assert "column 'a=b,c' has 1 cell written" in capsys.readouterr().err


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json") == 0
    assert "scientific" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--forbid-scientific", ""], "invalid --forbid-scientific value: '' (no name)"),
        (["--forbid-scientific", "  "], "invalid --forbid-scientific value: '  ' (no name)"),
        (
            ["--columns", "Codigo", "--forbid-scientific", "GTIN"],
            "--forbid-scientific checks column 'GTIN', which --columns leaves out",
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
    assert run(write_csv, "--forbid-scientific", "GTN") == 8
    assert "required column 'GTN' is missing" in capsys.readouterr().err
