"""Tests for ``--column-order LEFT<=RIGHT`` and ``LEFT<RIGHT`` (issue #284)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import build_report, evaluate, read_table
from csv_quality_report.checks import CHECK_COLUMN_ORDER, CHECK_REQUIRED_COLUMN, CheckResult
from csv_quality_report.cli import main
from csv_quality_report.profile import (
    OrderProfile,
    Report,
    column_order,
    profile_file,
    profile_rows,
)

WriteCsv = Callable[..., Path]
DISPATCH = ("Despacho", "<=", "Entrega")
# A courier export: row 2 is delivered before its dispatch, row 3 the same day,
# row 4 has a missing dispatch, row 5 a pending delivery, row 6 a date and a
# later date-time.
DATA = (
    "Guia;Despacho;Entrega;Pedido;Entregado\n"
    "A1;05/10/2026;07/10/2026;10;10\n"
    "A2;08/10/2026;06/10/2026;5;6\n"
    "A3;06/10/2026;06/10/2026;4;4\n"
    "A4;s/d;06/10/2026;3;3\n"
    "A5;06/10/2026;pendiente;2;0\n"
    "A6;06/10/2026;06/10/2026 14:30;1;1\n"
)


def orders(
    content: str, *triples: tuple[str, str, str], **options: object
) -> tuple[OrderProfile, ...]:
    header, *rows = [line.split(";") for line in content.splitlines()]
    return profile_rows(header, rows, column_orders=triples, **options).orders  # type: ignore[arg-type]


def dispatch(**options: object) -> OrderProfile:
    (found,) = orders(DATA, DISPATCH, date_order="dmy", na_tokens=("s/d",), **options)
    return found


# --- measuring in the profile ------------------------------------------------


def test_rows_out_of_order_uncomparable_and_skipped_are_counted() -> None:
    assert dispatch() == OrderProfile(
        left="Despacho",
        operator="<=",
        right="Entrega",
        checked=5,
        skipped=1,
        violations=1,
        uncomparable=1,
        examples=((2, "08/10/2026", "06/10/2026"),),
        uncomparable_examples=((5, "06/10/2026", "pendiente"),),
    )


def test_strict_order_also_fails_equal_values() -> None:
    (found,) = orders(DATA, ("Despacho", "<", "Entrega"), date_order="dmy", na_tokens=("s/d",))
    # Row 3 has the same day on both sides; row 6 compares a date (midnight)
    # with 14:30 of that day, which keeps the order.
    assert [row for row, _, _ in found.examples] == [2, 3]
    assert found.violations == 2


def test_numbers_compare_with_the_reading_rules() -> None:
    content = "Pedido;Entregado\n12,5;12,50\n3,25;3,3\n1.000;999\n(5);-6\n"
    (found,) = orders(
        content,
        ("Entregado", "<=", "Pedido"),
        decimal_comma=True,
        thousands=".",
        accounting_negatives=True,
    )
    # 12,50 equals 12,5; 3,3 > 3,25 breaks it; 999 < 1.000 and -6 < (5) keep it.
    assert found.examples == ((2, "3,3", "3,25"),)
    assert (found.checked, found.violations, found.uncomparable) == (4, 1, 0)


def test_integers_and_decimals_compare_exactly() -> None:
    # 2**53 + 1 is not a float: as floats both sides would be equal.
    content = f"A;B\n{2**53 + 1};9007199254740992.0\n"
    (found,) = orders(content, ("A", "<=", "B"))
    assert found.violations == 1


def test_number_affixes_are_removed_before_comparing() -> None:
    content = "Bruto;Descuento\n$ 100;$ 120\nUS$ 50;US$ 5\n"
    (found,) = orders(content, ("Descuento", "<=", "Bruto"), number_affixes=("$", "US$"))
    assert found.examples == ((1, "$ 120", "$ 100"),)


def test_month_names_are_read_with_the_date_order() -> None:
    content = "Desde;Hasta\n05-oct-2026;03-oct-2026\n"
    (plain,) = orders(content, ("Desde", "<=", "Hasta"), date_order="dmy")
    assert (plain.violations, plain.uncomparable) == (0, 1)
    (named,) = orders(content, ("Desde", "<=", "Hasta"), date_order="dmy", month_names=True)
    assert (named.violations, named.uncomparable) == (1, 0)


def test_times_with_offsets_compare_as_instants() -> None:
    content = (
        "Salida;Llegada\n"
        "2026-10-05T10:00:00-04:00;2026-10-05T15:30:00+02:00\n"  # 14:00Z then 13:30Z
        "2026-10-05T10:00:00-04:00;2026-10-05T16:30:00+02:00\n"  # 14:00Z then 14:30Z
    )
    (found,) = orders(content, ("Salida", "<=", "Llegada"))
    assert (found.checked, found.violations, found.uncomparable) == (2, 1, 0)
    assert found.examples[0][0] == 1


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("2026-10-05T10:00:00-04:00", "2026-10-06"),  # an offset and none
        ("2026-10-05", "2026-10-06T10:00:00Z"),
        ("5", "2026-10-06"),  # a number and a date
        ("true", "false"),  # booleans are not ordered
        ("abc", "abd"),  # text is not compared as text
        ("1", "x"),
    ],
    ids=["aware-naive", "naive-aware", "number-date", "bools", "text", "number-text"],
)
def test_values_of_different_kinds_cannot_be_compared(left: str, right: str) -> None:
    (found,) = orders(f"A;B\n{left};{right}\n", ("A", "<=", "B"))
    assert (found.checked, found.violations, found.uncomparable) == (1, 0, 1)
    assert found.uncomparable_examples == ((1, left, right),)


def test_a_missing_cell_skips_the_row_even_next_to_text() -> None:
    content = "A;B\n;x\nx; \nn/d;1\n1;N/D\n"
    (found,) = orders(content, ("A", "<=", "B"), na_tokens=("n/d",), na_ignore_case=True)
    assert (found.checked, found.skipped, found.uncomparable) == (0, 4, 0)


def test_cells_are_stripped_and_examples_show_them_stripped() -> None:
    (found,) = orders("A;B\n  7 ; 3\t\n", ("A", "<=", "B"))
    assert found.examples == ((1, "7", "3"),)


def test_examples_are_limited_to_top_n_and_counts_stay_exact() -> None:
    content = "A;B\n" + "".join(f"{i + 1};{i}\n" for i in range(6)) + "x;1\n" * 4
    (found,) = orders(content, ("A", "<=", "B"), top_n=2)
    assert (found.violations, found.uncomparable) == (6, 4)
    assert [row for row, _, _ in found.examples] == [1, 2]
    assert [row for row, _, _ in found.uncomparable_examples] == [7, 8]
    (none,) = orders(content, ("A", "<=", "B"), top_n=0)
    assert none.examples == none.uncomparable_examples == ()


def test_row_numbers_continue_across_batches(write_csv: WriteCsv) -> None:
    rows = "".join(f"{i};{i}\n" for i in range(25_000))
    path = write_csv("A;B\n" + rows + "2;1\n")
    report = profile_file(path, delimiter=";", column_orders=[("A", "<=", "B")])
    assert report.orders[0].examples == ((25_001, "2", "1"),)
    assert report.orders[0].checked == 25_001
    stopped = profile_file(path, delimiter=";", max_rows=25_000, column_orders=[("A", "<=", "B")])
    assert stopped.orders[0].violations == 0


def test_columns_left_out_by_columns_are_still_compared() -> None:
    (found,) = orders(DATA, DISPATCH, date_order="dmy", na_tokens=("s/d",), columns=["Guia"])
    assert found.violations == 1


def test_orders_on_one_column_share_its_parsed_values() -> None:
    found = orders(
        DATA,
        DISPATCH,
        ("Despacho", "<", "Entrega"),
        ("Entregado", "<=", "Pedido"),
        DISPATCH,  # a repeated order counts once
        date_order="dmy",
        na_tokens=("s/d",),
    )
    assert [(o.left, o.operator, o.right) for o in found] == [
        DISPATCH,
        ("Despacho", "<", "Entrega"),
        ("Entregado", "<=", "Pedido"),
    ]
    assert [o.violations for o in found] == [1, 2, 1]


def test_unknown_columns_are_skipped_in_the_profile() -> None:
    assert orders(DATA, ("Despacho", "<=", "Nada"), ("Nada", "<", "Entrega")) == ()


def test_no_orders_no_profiles(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv(DATA), delimiter=";").orders == ()


def test_build_report_measures_the_same(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    options = {"date_order": "dmy", "na_tokens": ("s/d",), "column_orders": [DISPATCH]}
    streamed = profile_file(path, delimiter=";", **options)  # type: ignore[arg-type]
    loaded = build_report(read_table(path, delimiter=";"), **options)  # type: ignore[arg-type]
    assert streamed.orders == loaded.orders == (dispatch(),)


@pytest.mark.parametrize(
    ("triple", "message"),
    [
        (("A", "=<", "B"), "must be one of <=, <"),
        (("A", ">", "B"), "must be one of <=, <"),
        (("", "<=", "B"), "needs two column names"),
        (("A", "<=", ""), "needs two column names"),
        (("A", "<=", 3), "needs two column names"),
        ((None, "<=", "B"), "needs two column names"),
        (("A", "<=", "A"), "two different columns"),
    ],
    ids=["swapped", "greater", "no-left", "no-right", "int", "none", "same"],
)
def test_invalid_orders_are_refused_before_reading(
    triple: tuple[str, str, str], message: str
) -> None:
    def rows() -> object:
        raise AssertionError("no row may be read")
        yield  # pragma: no cover

    with pytest.raises(ValueError, match=message):
        profile_rows(["A", "B"], rows(), column_orders=[triple])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=message):
        column_order(*triple)


# --- the check ---------------------------------------------------------------


def report_of(write_csv: WriteCsv, *triples: tuple[str, str, str], **options: object) -> Report:
    return profile_file(
        write_csv(DATA),
        delimiter=";",
        date_order="dmy",
        na_tokens=("s/d",),
        column_orders=triples,
        **options,  # type: ignore[arg-type]
    )


def test_evaluate_fails_and_describes(write_csv: WriteCsv) -> None:
    (check,) = evaluate(report_of(write_csv, DISPATCH), column_orders=[DISPATCH])
    assert check.check == CHECK_COLUMN_ORDER
    assert (check.column, check.value, check.limit, check.passed) == (None, 2, 0, False)
    assert (check.checked, check.skipped, check.violations, check.uncomparable) == (5, 1, 1, 1)
    assert check.describe() == (
        "columns 'Despacho' <= 'Entrega' fail in 2 of 5 checked rows: "
        '1 out of order (data row 2: "08/10/2026" > "06/10/2026"); '
        '1 cannot be compared (data row 5: "06/10/2026", "pendiente"); '
        "1 row with a missing cell was skipped"
    )


def test_strict_order_is_described_with_greater_or_equal(write_csv: WriteCsv) -> None:
    strict = ("Pedido", "<", "Entregado")
    (check,) = evaluate(report_of(write_csv, strict), column_orders=[strict])
    assert check.describe() == (
        "columns 'Pedido' < 'Entregado' fail in 5 of 6 checked rows: 5 out of order "
        '(data row 1: "10" >= "10"; data row 3: "4" >= "4"; data row 4: "3" >= "3")'
    )  # the first --top 3 of the 5 rows


def test_counts_without_examples_with_top_zero(write_csv: WriteCsv) -> None:
    (check,) = evaluate(report_of(write_csv, DISPATCH, top_n=0), column_orders=[DISPATCH])
    assert check.describe() == (
        "columns 'Despacho' <= 'Entrega' fail in 2 of 5 checked rows: 1 out of order; "
        "1 cannot be compared; 1 row with a missing cell was skipped"
    )


def test_evaluate_passes(write_csv: WriteCsv) -> None:
    order = ("Entregado", "<=", "Pedido")
    path = write_csv(DATA.replace("A2;08/10/2026;06/10/2026;5;6", "A2;08/10/2026;06/10/2026;5;5"))
    report = profile_file(path, delimiter=";", column_orders=[order])
    (check,) = evaluate(report, column_orders=[order])
    assert check.passed and check.value == 0
    assert check.describe() == "columns 'Entregado' <= 'Pedido' hold in all 6 checked rows"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("A;B\n1;2\n", "columns 'A' <= 'B' hold in the checked row"),
        ("A;B\n1;2\n;3\n", "columns 'A' <= 'B' hold in the checked row; 1 row with a missing "),
        (
            "A;B\n;2\n3;\n",
            "columns 'A' <= 'B' have no rows with both values to check; 2 rows with a missing "
            "cell were skipped",
        ),
        ("A;B\n", "columns 'A' <= 'B' have no rows with both values to check"),
        ("A;B\nx;1\n", "columns 'A' <= 'B' fail in 1 of 1 checked row: 1 cannot be compared"),
    ],
    ids=["one", "one-skipped", "none-skipped", "empty", "one-uncomparable"],
)
def test_messages_for_few_rows(write_csv: WriteCsv, content: str, message: str) -> None:
    order = ("A", "<=", "B")
    report = profile_file(write_csv(content), delimiter=";", column_orders=[order])
    (check,) = evaluate(report, column_orders=[order])
    assert check.describe().startswith(message)


def test_evaluate_needs_the_order_in_the_report(write_csv: WriteCsv) -> None:
    report = report_of(write_csv, DISPATCH)
    with pytest.raises(ValueError, match="'Despacho' < 'Entrega' have a column_order check"):
        evaluate(report, column_orders=[("Despacho", "<", "Entrega")])
    with pytest.raises(ValueError, match="must be one of"):
        evaluate(report, column_orders=[("Despacho", ">", "Entrega")])


def test_unknown_columns_fail_as_required_columns(write_csv: WriteCsv) -> None:
    unknown = ("Despacho", "<=", "Entrega2")
    report = report_of(write_csv, unknown, DISPATCH)
    assert len(report.orders) == 1  # the unknown order is not measured
    checks = evaluate(report, column_orders=[unknown, DISPATCH, unknown])
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_COLUMN_ORDER, None, False),
        (CHECK_REQUIRED_COLUMN, "Entrega2", False),
    ]
    # An unknown name needs no profile, since nothing could be measured.
    (check,) = evaluate(report_of(write_csv), column_orders=[("Nada", "<", "Entrega")])
    assert (check.check, check.column) == (CHECK_REQUIRED_COLUMN, "Nada")


def test_an_unknown_name_gets_a_hint(write_csv: WriteCsv) -> None:
    order = ("Despacho", "<=", "Entrega ")
    checks = evaluate(report_of(write_csv, order), column_orders=[order])
    assert [c.describe() for c in checks] == [
        "required column 'Entrega ' is missing (columns: Guia, Despacho, Entrega, Pedido, "
        "Entregado); did you mean 'Entrega'?"
    ]


def test_columns_outside_the_selection_are_checked(write_csv: WriteCsv) -> None:
    report = report_of(write_csv, DISPATCH, columns=["Guia"])
    (check,) = evaluate(report, column_orders=[DISPATCH])
    assert check.violations == 1


def test_the_result_fields_default_to_empty() -> None:
    check = CheckResult(check="max_duplicates", column=None, limit=0, value=0, passed=True)
    assert check.order is None
    assert (check.checked, check.violations, check.uncomparable) == (0, 0, 0)
    assert check.out_of_order == check.uncomparable_rows == ()


# --- command line ------------------------------------------------------------


def run(write_csv: WriteCsv, *args: str) -> int:
    return main([str(write_csv(DATA)), "--delimiter", ";", "--date-order", "dmy", *args])


def test_cli_fails_with_exit_code_8(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run(
        write_csv,
        "--na",
        "s/d",
        "--column-order",
        "Despacho <= Entrega",
        "--column-order",
        "Entregado<=Pedido",
        "--column-order",
        "Despacho<=Entrega",
    )
    out, err = capsys.readouterr()
    assert code == 8
    assert err.splitlines() == [
        "check failed: columns 'Despacho' <= 'Entrega' fail in 2 of 5 checked rows: "
        '1 out of order (data row 2: "08/10/2026" > "06/10/2026"); '
        '1 cannot be compared (data row 5: "06/10/2026", "pendiente"); '
        "1 row with a missing cell was skipped",
        "check failed: columns 'Entregado' <= 'Pedido' fail in 1 of 6 checked rows: "
        '1 out of order (data row 2: "6" > "5")',
    ]
    assert "## Checks: FAILED (2 of 2 failed)" in out
    assert "- FAIL: columns 'Despacho' &lt;= 'Entrega' fail in 2 of 5 checked rows" in out


def test_cli_passes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv("Desde;Hasta\n01/10/2026;02/10/2026\n")
    args = [str(path), "--delimiter", ";", "--date-order", "dmy", "--column-order", "Desde<Hasta"]
    assert main(args) == 0
    out, err = capsys.readouterr()
    assert "- pass: columns 'Desde' &lt; 'Hasta' hold in the checked row" in out
    assert err == ""


def test_cli_text_columns_fail_as_uncomparable(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--column-order", "Guia<Pedido", "--top", "0") == 8
    assert capsys.readouterr().err == (
        "check failed: columns 'Guia' < 'Pedido' fail in 6 of 6 checked rows: "
        "6 cannot be compared\n"
    )


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(write_csv, "--na", "s/d", "--column-order", "Despacho<=Entrega", "--format", "json")
    assert code == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check == {
        "check": "column_order",
        "column": None,
        "limit": 0,
        "value": 2,
        "passed": False,
        "left": "Despacho",
        "operator": "<=",
        "right": "Entrega",
        "checked": 5,
        "skipped": 1,
        "violations": 1,
        "uncomparable": 1,
        "out_of_order": [{"row": 2, "left": "08/10/2026", "right": "06/10/2026"}],
        "uncomparable_rows": [{"row": 5, "left": "06/10/2026", "right": "pendiente"}],
    }


def test_cli_right_name_may_contain_less_than(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("A;B<C\n1;2\n3;2\n")
    assert main([str(path), "--delimiter", ";", "--column-order", "A<=B<C"]) == 8
    assert "columns 'A' <= 'B<C' fail in 1 of 2" in capsys.readouterr().err
    assert main([str(path), "--delimiter", ";", "--column-order", "A<B<C"]) == 8
    assert "columns 'A' < 'B<C' fail in 1 of 2" in capsys.readouterr().err


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json") == 0
    plain = capsys.readouterr().out
    assert "column_order" not in plain and "uncomparable" not in plain


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("Despacho", "use LEFT<=RIGHT or LEFT<RIGHT"),
        ("Despacho>=Entrega", "use LEFT<=RIGHT or LEFT<RIGHT"),
        ("<=Entrega", "use LEFT<=RIGHT or LEFT<RIGHT"),
        ("Despacho<=", "use LEFT<=RIGHT or LEFT<RIGHT"),
        ("Despacho <=  ", "use LEFT<=RIGHT or LEFT<RIGHT"),
        ("  <Entrega", "use LEFT<=RIGHT or LEFT<RIGHT"),
        ("Despacho<", "use LEFT<=RIGHT or LEFT<RIGHT"),
        ("Despacho <= Despacho", "two different columns, not 'Despacho' twice"),
    ],
    ids=[
        "no-op",
        "greater",
        "no-left",
        "no-right",
        "blank-right",
        "blank-left",
        "lt-empty",
        "same",
    ],
)
def test_cli_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], value: str, message: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(write_csv, "--column-order", value)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "invalid --column-order value" in err and message in err


def test_cli_unknown_column(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--column-order", "Despacho<=Llegada") == 8
    assert "required column 'Llegada' is missing" in capsys.readouterr().err
