"""Tests for ``--forbid-untrimmed NAME`` (issue #316)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import build_report, evaluate, read_table
from csv_quality_report.checks import CHECK_REQUIRED_COLUMN, CHECK_UNTRIMMED
from csv_quality_report.cli import main
from csv_quality_report.profile import UntrimmedProfile, profile_file

WriteCsv = Callable[..., Path]
# A warehouse stock export: codes padded from a fixed-width ERP field, one
# with a non-breaking space pasted from a web page and one with a tab. The
# padded " s/d " and the blank cell are missing, never untrimmed; the
# warehouse names are clean.
DATA = (
    "Código;Depósito;Stock\n"
    "ALM01   ;Central;12\n"
    "ALM01   ;Central;3\n"
    " SKU-1001;Norte;5\n"
    " s/d ;Sur;7\n"
    "   ;Sur;1\n"
    "ALM02\t;Sur;0\n"
    "ALM03;Norte;4\n"
)


def untrimmed(path: Path, name: str = "Código", **options: object) -> UntrimmedProfile:
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        forbid_untrimmed=(name,),
        **options,  # type: ignore[arg-type]
    )
    (found,) = report.untrimmed_values
    return found


# --- measuring in the profile ------------------------------------------------


def test_cells_and_examples_as_read(write_csv: WriteCsv) -> None:
    assert untrimmed(write_csv(DATA)) == UntrimmedProfile(
        column="Código",
        cells=4,
        examples=(("ALM01   ", 2), (" SKU-1001", 1), ("ALM02\t", 1)),
    )


def test_cells_agree_with_the_column_untrimmed_count(write_csv: WriteCsv) -> None:
    report = profile_file(
        write_csv(DATA), delimiter=";", na_tokens=("s/d",), forbid_untrimmed=("Código",)
    )
    (column, *_) = report.columns
    assert column.untrimmed == report.untrimmed_values[0].cells == 4


def test_a_clean_column(write_csv: WriteCsv) -> None:
    assert untrimmed(write_csv(DATA), "Depósito") == UntrimmedProfile(column="Depósito", cells=0)


def test_missing_cells_are_not_untrimmed(write_csv: WriteCsv) -> None:
    path = write_csv("Código\n s/d \n   \n\n S/D \n")
    assert untrimmed(path) == UntrimmedProfile(column="Código", cells=1, examples=((" S/D ", 1),))
    folded = untrimmed(path, na_ignore_case=True)
    assert folded == UntrimmedProfile(column="Código", cells=0)


def test_distinct_spellings_of_one_value_are_listed_apart(write_csv: WriteCsv) -> None:
    # They are one value in the report, but each spelling needs its own fix.
    path = write_csv("Código\nA \n A\nA \nA\n")
    found = untrimmed(path)
    assert found == UntrimmedProfile(column="Código", cells=3, examples=(("A ", 2), (" A", 1)))


def test_unicode_whitespace_counts(write_csv: WriteCsv) -> None:
    # What str.strip() removes: the narrow no-break space of number formats,
    # the ideographic space and a line separator, as written by some exports.
    path = write_csv("Código\nA \n　B\nC \nD​\n")
    found = untrimmed(path)
    assert found.cells == 3
    assert [value for value, _ in found.examples] == ["A ", "　B", "C "]


def test_top_limits_the_examples_not_the_count(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    one = untrimmed(path, top_n=1)
    assert (one.cells, one.examples) == (4, (("ALM01   ", 2),))
    none = untrimmed(path, top_n=0)
    assert (none.cells, none.examples) == (4, ())


def test_the_most_frequent_texts_come_first(write_csv: WriteCsv) -> None:
    path = write_csv("Código\nB \nA \nC\nA \n A\n A\n A\n")
    assert untrimmed(path).examples == ((" A", 3), ("A ", 2), ("B ", 1))
    assert untrimmed(path, top_n=1).examples == ((" A", 3),)


def test_ties_keep_the_first_seen_value(write_csv: WriteCsv) -> None:
    path = write_csv("Código\nB \nA \n A\n")
    assert untrimmed(path).examples == (("B ", 1), ("A ", 1), (" A", 1))


def test_a_value_seen_only_in_a_later_batch_is_found(write_csv: WriteCsv) -> None:
    rows = "".join(f"ALM{i};1\n" for i in range(25_000))
    path = write_csv("Código;x\n" + rows + "ALM9 ;1\n")
    assert untrimmed(path).examples == (("ALM9 ", 1),)
    assert untrimmed(path, max_rows=25_000).cells == 0


def test_other_columns_keep_no_padded_texts(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA), delimiter=";", forbid_untrimmed=("Depósito",))
    assert report.untrimmed_values == (UntrimmedProfile(column="Depósito", cells=0),)
    assert report.columns[0].untrimmed == 5  # still measured, as without the option


def test_unprofiled_and_unknown_columns_are_skipped(write_csv: WriteCsv) -> None:
    report = profile_file(
        write_csv(DATA),
        delimiter=";",
        columns=("Stock",),
        forbid_untrimmed=("Código", "Nada"),
    )
    assert report.untrimmed_values == ()


def test_build_report_measures_the_same(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    table = read_table(path, delimiter=";")
    built = build_report(table, na_tokens=("s/d",), forbid_untrimmed=["Código"])
    assert built.untrimmed_values == (untrimmed(path),)


def test_no_names_no_profiles(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv(DATA), delimiter=";").untrimmed_values == ()


def test_the_rest_of_the_report_is_unchanged(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    plain = profile_file(path, delimiter=";", na_tokens=("s/d",))
    gated = profile_file(path, delimiter=";", na_tokens=("s/d",), forbid_untrimmed=["Código"])
    assert plain.columns == gated.columns
    assert gated.untrimmed_values != ()


# --- evaluate() ----------------------------------------------------------------


def checked(path: Path, **options: object) -> list[tuple[str, str | None, bool, str]]:
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        forbid_untrimmed=("Código", "Depósito"),
        **options,  # type: ignore[arg-type]
    )
    checks = evaluate(report, forbid_untrimmed=["Código", "Depósito", "Código"])
    return [(c.check, c.column, c.passed, c.describe()) for c in checks]


def test_evaluate_fails_passes_and_describes(write_csv: WriteCsv) -> None:
    assert checked(write_csv(DATA)) == [
        (
            CHECK_UNTRIMMED,
            "Código",
            False,
            "column 'Código' has 4 cells with leading or trailing whitespace (joins and "
            "lookups on the column miss them; trim the column before exporting): "
            '"ALM01   " in 2 cells, "\\u00a0SKU-1001" in 1 cell, "ALM02\\u0009" in 1 cell',
        ),
        (
            CHECK_UNTRIMMED,
            "Depósito",
            True,
            "column 'Depósito' has no cells with leading or trailing whitespace",
        ),
    ]


def test_evaluate_singular_and_without_examples(write_csv: WriteCsv) -> None:
    path = write_csv("Código;Depósito\nA ;x\nB;y\n")
    (codigo, _) = checked(path)
    assert codigo[3] == (
        "column 'Código' has 1 cell with leading or trailing whitespace (joins and lookups "
        'on the column miss them; trim the column before exporting): "A " in 1 cell'
    )
    (codigo, _) = checked(path, top_n=0)
    assert codigo[3] == (
        "column 'Código' has 1 cell with leading or trailing whitespace (joins and lookups "
        "on the column miss them; trim the column before exporting)"
    )


def test_evaluate_needs_the_names_in_the_report(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA), delimiter=";")
    with pytest.raises(ValueError, match="'Código' has an untrimmed check but the report"):
        evaluate(report, forbid_untrimmed=["Código"])


def test_unknown_and_unprofiled_columns(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    report = profile_file(path, delimiter=";")
    checks = evaluate(report, forbid_untrimmed=["Codigo"])
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "Codigo", False)
    ]
    narrow = profile_file(path, delimiter=";", columns=("Stock",))
    with pytest.raises(ValueError, match="column 'Código' has a per-column check"):
        evaluate(narrow, forbid_untrimmed=["Código"])


def test_a_padded_header_name_is_suggested(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("Código ;x\nA;1\n"), delimiter=";")
    (check,) = evaluate(report, forbid_untrimmed=["Código"])
    assert (check.check, check.hint) == (CHECK_REQUIRED_COLUMN, "Código ")


# --- command line --------------------------------------------------------------


def run(write_csv: WriteCsv, *args: str, data: str = DATA) -> int:
    return main([str(write_csv(data)), "--delimiter", "auto", "--na", "s/d", *args])


def test_cli_fails(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(write_csv, "--top", "1", "--forbid-untrimmed", "Código")
    out, err = capsys.readouterr()
    assert code == 8
    assert err == (
        "check failed: column 'Código' has 4 cells with leading or trailing whitespace "
        "(joins and lookups on the column miss them; trim the column before exporting): "
        '"ALM01   " in 2 cells\n'
    )
    assert "- FAIL: column 'Código' has 4 cells with leading or trailing whitespace" in out


def test_cli_passes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--forbid-untrimmed", "Depósito") == 0
    out = capsys.readouterr().out
    assert "- pass: column 'Depósito' has no cells with leading or trailing whitespace" in out


def test_cli_markdown_escapes_the_values(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    data = "Código;x\n<b>A|B</b> ;1\n"
    assert run(write_csv, "--forbid-untrimmed", "Código", data=data) == 8
    out = capsys.readouterr().out
    (line,) = [line for line in out.splitlines() if line.startswith("- FAIL")]
    assert "<b>" not in line
    assert "A\\|B" in line


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--format", "json", "--forbid-untrimmed", "Código") == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check == {
        "check": "untrimmed",
        "column": "Código",
        "limit": 0,
        "value": 4,
        "passed": False,
        "untrimmed_values": {"ALM01   ": 2, " SKU-1001": 1, "ALM02\t": 1},
    }


def test_cli_json_of_a_passing_check(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json", "--forbid-untrimmed", "Depósito") == 0
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check["untrimmed_values"] == {}
    assert check["passed"] is True


def test_cli_repeated_name_gives_one_check(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ("--format", "json", "--forbid-untrimmed", "Código", "--forbid-untrimmed", "Código")
    assert run(write_csv, *args) == 8
    assert len(json.loads(capsys.readouterr().out)["checks"]) == 1


def test_cli_name_with_commas_and_equals_signs(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a=b,c;d\n1 ;1\n")
    assert main([str(path), "--delimiter", ";", "--forbid-untrimmed", "a=b,c"]) == 8
    assert "column 'a=b,c' has 1 cell with" in capsys.readouterr().err


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json") == 0
    assert "untrimmed_values" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--forbid-untrimmed", ""], "invalid --forbid-untrimmed value: '' (no name)"),
        (["--forbid-untrimmed", "  "], "invalid --forbid-untrimmed value: '  ' (no name)"),
        (
            ["--columns", "Stock", "--forbid-untrimmed", "Código"],
            "--forbid-untrimmed checks column 'Código', which --columns leaves out",
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
    assert run(write_csv, "--forbid-untrimmed", "Codigo") == 8
    assert "required column 'Codigo' is missing" in capsys.readouterr().err


def test_padded_texts_are_kept_only_when_asked() -> None:
    # Keeping them for every column would hold a second copy of the padded
    # values of columns no gate looks at.
    from csv_quality_report.profile import _ColumnAccumulator

    for keep in (False, True):
        acc = _ColumnAccumulator("Código")
        acc.counts.update(["A ", "A", " s/d ", "B"])
        acc.strip_counts({"", "s/d"}, keep_padded=keep)
        assert acc.untrimmed == 1
        assert acc.padded == ({"A ": 1} if keep else {})
