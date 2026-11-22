"""Tests for ``--require-when NAME COLUMN=VALUES`` (issue #318)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import build_report, evaluate, read_table
from csv_quality_report.checks import CHECK_REQUIRED_COLUMN, CHECK_REQUIRED_WHEN, CheckResult
from csv_quality_report.cli import main
from csv_quality_report.profile import (
    ConditionalProfile,
    Report,
    conditional_requirement,
    profile_file,
    profile_rows,
)

WriteCsv = Callable[..., Path]
DELIVERED = ("Entrega", "Estado", ("Entregado",))
# A courier export: the delivery date and the receiver are only filled once
# the parcel is delivered. Row 3 is delivered without a date, row 4 has the
# date as s/d, row 5 is delivered with a padded status and no receiver, and
# rows 2 and 6 are not delivered (no date needed).
DATA = (
    "Guia;Estado;Entrega;Recibio\n"
    "A1;Entregado;05/10/2026;Ana\n"
    "A2;En transito;;\n"
    "A3;Entregado;;Luis\n"
    "A4;Devuelto;s/d;\n"
    "A5; Entregado ;06/10/2026;  \n"
    "A6;entregado;;\n"
)


def conditionals(
    content: str, *rules: tuple[str, str, tuple[str, ...]], **options: object
) -> tuple[ConditionalProfile, ...]:
    header, *rows = [line.split(";") for line in content.splitlines()]
    return profile_rows(header, rows, required_when=rules, **options).conditionals  # type: ignore[arg-type]


def delivered(**options: object) -> ConditionalProfile:
    (found,) = conditionals(DATA, DELIVERED, na_tokens=("s/d",), **options)
    return found


# --- measuring in the profile ------------------------------------------------


def test_rows_that_meet_the_condition_and_lack_the_column_are_counted() -> None:
    # Rows 1, 3 and 5 are delivered (5 after stripping); only row 3 has no date.
    # Row 6 is "entregado" in lower case, which does not meet the condition.
    assert delivered() == ConditionalProfile(
        column="Entrega",
        when="Estado",
        values=("Entregado",),
        checked=3,
        missing=1,
        examples=((3, "Entregado"),),
    )


def test_several_values_and_na_tokens_count_as_missing() -> None:
    (found,) = conditionals(
        DATA, ("Entrega", "Estado", ("Entregado", "Devuelto")), na_tokens=("s/d",)
    )
    assert (found.checked, found.missing) == (4, 2)
    assert found.examples == ((3, "Entregado"), (4, "Devuelto"))
    # Without --na, s/d is a value, so the returned parcel has its date.
    (plain,) = conditionals(DATA, ("Entrega", "Estado", ("Entregado", "Devuelto")))
    assert (plain.checked, plain.missing, plain.examples) == (4, 1, ((3, "Entregado"),))


def test_whitespace_only_cells_are_missing() -> None:
    (found,) = conditionals(DATA, ("Recibio", "Estado", ("Entregado",)))
    assert (found.checked, found.missing, found.examples) == (3, 1, ((5, "Entregado"),))


def test_na_ignore_case_folds_the_missing_texts() -> None:
    content = "Estado;Entrega\nEntregado;S/D\nEntregado;s/d\nEntregado;01/10/2026\n"
    (exact,) = conditionals(content, DELIVERED, na_tokens=("s/d",))
    assert (exact.checked, exact.missing) == (3, 1)
    (folded,) = conditionals(content, DELIVERED, na_tokens=("s/d",), na_ignore_case=True)
    assert (folded.missing, [row for row, _ in folded.examples]) == (2, [1, 2])


def test_the_condition_is_compared_as_stripped_case_sensitive_text() -> None:
    content = "Estado;Entrega\n ENTREGADO ;\nEntregado ;\nEntregado.;\n"
    (upper,) = conditionals(content, ("Entrega", "Estado", ("ENTREGADO",)))
    assert (upper.checked, upper.missing, upper.examples) == (1, 1, ((1, "ENTREGADO"),))
    (title,) = conditionals(content, DELIVERED)
    # The non-breaking space is stripped like any whitespace; "Entregado." is another value.
    assert (title.checked, title.examples) == (1, ((2, "Entregado"),))


def test_a_missing_condition_cell_is_not_checked() -> None:
    content = "Estado;Entrega\n;\ns/d;\n"
    (found,) = conditionals(content, DELIVERED, na_tokens=("s/d",))
    assert (found.checked, found.missing) == (0, 0)


def test_examples_are_limited_to_top_n_and_counts_stay_exact() -> None:
    content = "Estado;Entrega\n" + "Entregado;\n" * 8
    (found,) = conditionals(content, DELIVERED, top_n=3)
    assert (found.checked, found.missing) == (8, 8)
    assert found.examples == ((1, "Entregado"), (2, "Entregado"), (3, "Entregado"))
    (none,) = conditionals(content, DELIVERED, top_n=0)
    assert (none.missing, none.examples) == (8, ())


def test_row_numbers_continue_across_batches(write_csv: WriteCsv) -> None:
    rows = "".join(f"Entregado;{i}\n" for i in range(25_000))
    path = write_csv("Estado;Entrega\n" + rows + "Entregado;\n")
    report = profile_file(path, delimiter=";", required_when=[DELIVERED])
    assert report.conditionals[0].examples == ((25_001, "Entregado"),)
    assert report.conditionals[0].checked == 25_001
    stopped = profile_file(path, delimiter=";", max_rows=25_000, required_when=[DELIVERED])
    assert (stopped.conditionals[0].checked, stopped.conditionals[0].missing) == (25_000, 0)


def test_columns_left_out_by_columns_are_still_checked() -> None:
    (found,) = conditionals(DATA, DELIVERED, na_tokens=("s/d",), columns=["Guia"])
    assert found.missing == 1


def test_repeated_requirements_give_one_profile_and_values_are_normalized() -> None:
    found = conditionals(
        DATA,
        DELIVERED,
        ("Entrega", "Estado", (" Entregado ", "Entregado")),
        ("Recibio", "Estado", ("Entregado",)),
    )
    assert [(c.column, c.values) for c in found] == [
        ("Entrega", ("Entregado",)),
        ("Recibio", ("Entregado",)),
    ]


def test_unknown_columns_are_skipped_in_the_profile() -> None:
    found = conditionals(
        DATA, ("Llegada", "Estado", ("Entregado",)), ("Entrega", "Situacion", ("A",))
    )
    assert found == ()


def test_no_requirements_no_profiles(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv(DATA), delimiter=";").conditionals == ()


def test_build_report_measures_the_same(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    options = {"na_tokens": ("s/d",), "required_when": [DELIVERED]}
    streamed = profile_file(path, delimiter=";", **options)  # type: ignore[arg-type]
    loaded = build_report(read_table(path, delimiter=";"), **options)  # type: ignore[arg-type]
    assert streamed.conditionals == loaded.conditionals == (delivered(),)


def test_a_one_shot_iterable_of_values_is_accepted() -> None:
    (found,) = conditionals(DATA, ("Entrega", "Estado", iter(["Entregado"])))  # type: ignore[arg-type]
    assert found.values == ("Entregado",)


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        (("", "Estado", ("A",)), "needs two column names"),
        (("Entrega", "", ("A",)), "needs two column names"),
        ((3, "Estado", ("A",)), "needs two column names"),
        (("Entrega", None, ("A",)), "needs two column names"),
        (("Estado", "Estado", ("A",)), "two different columns"),
        (("Entrega", "Estado", ()), "at least one value and no empty ones"),
        (("Entrega", "Estado", ("A", " ")), "at least one value and no empty ones"),
        (("Entrega", "Estado", "Entregado"), "a list of texts, not the text 'Entregado'"),
    ],
    ids=["no-column", "no-when", "int", "none", "same", "no-values", "blank-value", "str"],
)
def test_invalid_requirements_are_refused_before_reading(
    rule: tuple[str, str, tuple[str, ...]], message: str
) -> None:
    def rows() -> object:
        raise AssertionError("no row may be read")
        yield  # pragma: no cover

    with pytest.raises(ValueError, match=message):
        profile_rows(["Estado", "Entrega"], rows(), required_when=[rule])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=message):
        conditional_requirement(*rule)


# --- the check ---------------------------------------------------------------


def report_of(
    write_csv: WriteCsv, *rules: tuple[str, str, tuple[str, ...]], **options: object
) -> Report:
    return profile_file(
        write_csv(DATA),
        delimiter=";",
        na_tokens=("s/d",),
        required_when=rules,
        **options,  # type: ignore[arg-type]
    )


def test_evaluate_fails_and_describes(write_csv: WriteCsv) -> None:
    (check,) = evaluate(report_of(write_csv, DELIVERED), required_when=[DELIVERED])
    assert check.check == CHECK_REQUIRED_WHEN
    assert (check.column, check.value, check.limit, check.passed) == ("Entrega", 1, 0, False)
    assert (check.when, check.when_values, check.checked) == ("Estado", ("Entregado",), 3)
    assert check.missing_rows == ((3, "Entregado"),)
    assert check.describe() == (
        "column 'Entrega' is missing in 1 of 3 rows where 'Estado' is \"Entregado\" (data row 3)"
    )


def test_several_values_are_named_with_each_row(write_csv: WriteCsv) -> None:
    rule = ("Entrega", "Estado", ("Entregado", "Devuelto"))
    (check,) = evaluate(report_of(write_csv, rule), required_when=[rule])
    assert check.describe() == (
        "column 'Entrega' is missing in 2 of 4 rows where 'Estado' is one of "
        '"Entregado", "Devuelto" (data rows 3 ("Entregado"), 4 ("Devuelto"))'
    )


def test_more_failing_rows_than_listed_end_with_an_ellipsis(write_csv: WriteCsv) -> None:
    path = write_csv("Estado;Entrega\n" + "Entregado;\n" * 4)
    report = profile_file(path, delimiter=";", top_n=2, required_when=[DELIVERED])
    (check,) = evaluate(report, required_when=[DELIVERED])
    assert check.describe() == (
        "column 'Entrega' is missing in 4 of 4 rows where 'Estado' is \"Entregado\" "
        "(data rows 1, 2, ...)"
    )
    report = profile_file(path, delimiter=";", top_n=0, required_when=[DELIVERED])
    (check,) = evaluate(report, required_when=[DELIVERED])
    assert check.describe() == (
        "column 'Entrega' is missing in 4 of 4 rows where 'Estado' is \"Entregado\""
    )


def test_long_value_lists_are_shortened(write_csv: WriteCsv) -> None:
    values = tuple(f"E{i}" for i in range(12))
    path = write_csv("Estado;Entrega\nE0;\n")
    rule = ("Entrega", "Estado", values)
    (check,) = evaluate(
        profile_file(path, delimiter=";", required_when=[rule]), required_when=[rule]
    )
    assert check.describe() == (
        "column 'Entrega' is missing in 1 of 1 row where 'Estado' is one of "
        + ", ".join(f'"E{i}"' for i in range(10))
        + ', ... (12 values) (data row 1 ("E0"))'
    )


def test_invisible_characters_in_values_are_shown_escaped(write_csv: WriteCsv) -> None:
    path = write_csv("Estado;Entrega\nA​B;\n")
    rule = ("Entrega", "Estado", ("A​B",))
    (check,) = evaluate(
        profile_file(path, delimiter=";", required_when=[rule]), required_when=[rule]
    )
    assert check.describe() == (
        "column 'Entrega' is missing in 1 of 1 row where 'Estado' is \"A\\u200bB\" (data row 1)"
    )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            "Estado;Entrega\nEntregado;01/10/2026\nEn transito;\nEntregado;02/10/2026\n",
            "column 'Entrega' is present in all 2 rows where 'Estado' is \"Entregado\"",
        ),
        (
            "Estado;Entrega\nEntregado;01/10/2026\n",
            "column 'Entrega' is present in the row where 'Estado' is \"Entregado\"",
        ),
        (
            "Estado;Entrega\nEn transito;\n",
            "column 'Entrega' was not checked: no row where 'Estado' is \"Entregado\"",
        ),
    ],
    ids=["all", "one", "none"],
)
def test_evaluate_passes(write_csv: WriteCsv, content: str, message: str) -> None:
    report = profile_file(write_csv(content), delimiter=";", required_when=[DELIVERED])
    (check,) = evaluate(report, required_when=[DELIVERED])
    assert check.passed
    assert check.value == 0
    assert check.describe() == message


def test_evaluate_needs_the_requirement_in_the_report(write_csv: WriteCsv) -> None:
    report = report_of(write_csv)
    with pytest.raises(ValueError, match="has a required_when check on 'Estado' but the report"):
        evaluate(report, required_when=[DELIVERED])
    other = ("Entrega", "Estado", ("Devuelto",))
    with pytest.raises(ValueError, match="was not profiled with it"):
        evaluate(report_of(write_csv, DELIVERED), required_when=[other])


def test_evaluate_validates_the_requirement(write_csv: WriteCsv) -> None:
    with pytest.raises(ValueError, match="two different columns"):
        evaluate(report_of(write_csv), required_when=[("Estado", "Estado", ("A",))])


def test_unknown_columns_fail_as_required_columns(write_csv: WriteCsv) -> None:
    rules = [("Llegada", "Estado", ("Entregado",)), ("Entrega", "Situacion", ("A",))]
    checks = evaluate(report_of(write_csv, *rules), required_when=rules)
    # Only the unknown names give a check; the known name of each pair does not.
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "Llegada", False),
        (CHECK_REQUIRED_COLUMN, "Situacion", False),
    ]


def test_an_unknown_name_gets_a_hint(write_csv: WriteCsv) -> None:
    rule = ("Entrega ", "Estado", ("Entregado",))
    (check,) = evaluate(report_of(write_csv, rule), required_when=[rule])
    assert check.hint == "Entrega"


def test_columns_outside_the_selection_are_checked(write_csv: WriteCsv) -> None:
    report = report_of(write_csv, DELIVERED, columns=["Guia"])
    (check,) = evaluate(report, required_when=[DELIVERED])
    assert (check.check, check.value) == (CHECK_REQUIRED_WHEN, 1)


def test_the_result_fields_default_to_empty() -> None:
    check = CheckResult(check="max_duplicates", column=None, limit=0, value=0, passed=True)
    assert (check.when, check.when_values, check.missing_rows) == ("", (), ())


# --- command line ------------------------------------------------------------


def run(write_csv: WriteCsv, *args: str) -> int:
    return main([str(write_csv(DATA)), "--delimiter", ";", *args])


def test_cli_fails_with_exit_code_8(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run(
        write_csv,
        "--na",
        "s/d",
        "--require-when",
        "Entrega",
        "Estado=Entregado,Devuelto",
        "--require-when",
        "Recibio",
        "Estado=Entregado",
        "--require-when",
        "Entrega",
        "Estado=Entregado, Devuelto",
    )
    out, err = capsys.readouterr()
    assert code == 8
    assert err.splitlines() == [
        "check failed: column 'Entrega' is missing in 2 of 4 rows where 'Estado' is one of "
        '"Entregado", "Devuelto" (data rows 3 ("Entregado"), 4 ("Devuelto"))',
        "check failed: column 'Recibio' is missing in 1 of 3 rows where 'Estado' is "
        '"Entregado" (data row 5)',
    ]
    assert "## Checks: FAILED (2 of 2 failed)" in out


def test_cli_passes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--require-when", "Guia", "Estado=Entregado") == 0
    out, err = capsys.readouterr()
    assert "- pass: column 'Guia' is present in all 3 rows where 'Estado' is" in out
    assert err == ""


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(
        write_csv,
        "--na",
        "s/d",
        "--require-when",
        "Entrega",
        "Estado=Entregado",
        "--format",
        "json",
    )
    assert code == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check == {
        "check": "required_when",
        "column": "Entrega",
        "limit": 0,
        "value": 1,
        "passed": False,
        "when": "Estado",
        "values": ["Entregado"],
        "checked": 3,
        "missing": 1,
        "rows": [{"row": 3, "value": "Entregado"}],
    }


def test_cli_names_may_contain_equals_and_commas(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("Estado=final;Nro, guia\nOK;\nOK;G1\n")
    assert (
        main([str(path), "--delimiter", ";", "--require-when", "Nro, guia", "Estado=final=OK"]) == 8
    )
    assert (
        "column 'Nro, guia' is missing in 1 of 2 rows where 'Estado=final' is \"OK\""
        in capsys.readouterr().err
    )


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json") == 0
    plain = capsys.readouterr().out
    assert "required_when" not in plain and '"when"' not in plain


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (["Entrega", "Estado"], "use NAME COLUMN=VALUE,VALUE"),
        (["Entrega", "=Entregado"], "use NAME COLUMN=VALUE,VALUE"),
        (["Entrega", "  =Entregado"], "use NAME COLUMN=VALUE,VALUE"),
        (["  ", "Estado=Entregado"], "use NAME COLUMN=VALUE,VALUE"),
        (["Entrega", "Estado="], "at least one value and no empty ones"),
        (["Entrega", "Estado=A,,B"], "at least one value and no empty ones"),
        (["Estado", "Estado=A"], "two different columns, not 'Estado' twice"),
    ],
    ids=["no-equals", "no-column", "blank-column", "blank-name", "no-values", "empty", "same"],
)
def test_cli_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], values: list[str], message: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(write_csv, "--require-when", *values)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "argument --require-when: invalid --require-when value" in err and message in err


def test_cli_needs_two_arguments(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        run(write_csv, "--require-when", "Entrega")
    assert exc.value.code == 2
    assert "argument --require-when: expected 2 arguments" in capsys.readouterr().err


def test_cli_unknown_column(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--require-when", "Llegada", "Estado=Entregado") == 8
    assert "required column 'Llegada' is missing" in capsys.readouterr().err
