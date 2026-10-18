"""Tests for ``--allowed-values NAME=V1,V2,...`` (issue #153)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import build_report, evaluate, read_table
from csv_quality_report.checks import CHECK_ALLOWED_VALUES, CHECK_REQUIRED_COLUMN
from csv_quality_report.cli import main
from csv_quality_report.profile import DomainProfile, allowed_list, profile_file

WriteCsv = Callable[..., Path]
DATA = (
    "Guía;Estado;Moneda\n"
    "A1;Entregado;PYG\n"
    "A2; Entregado ;USD\n"
    "A3;Devuelto;usd\n"
    "A4;;PYG\n"
    "A5;s/d;EUR\n"
    "A6;Entregdo;EUR\n"
    "A7;Devuelto;PYG\n"
)
STATUS = ("Entregado", "En tránsito", "Pendiente")


def domain(path: Path, name: str, allowed: tuple[str, ...], top_n: int = 5) -> DomainProfile:
    report = profile_file(
        path, delimiter=";", na_tokens=("s/d",), top_n=top_n, allowed_values={name: allowed}
    )
    (found,) = report.domains
    return found


# --- measuring in the profile ------------------------------------------------


def test_cells_outside_the_list_are_counted_exactly(write_csv: WriteCsv) -> None:
    found = domain(write_csv(DATA), "Estado", STATUS)
    # " Entregado " is stripped; "" and "s/d" are missing and not checked.
    assert found == DomainProfile(
        column="Estado",
        allowed=STATUS,
        unexpected=3,
        examples=(("Devuelto", 2), ("Entregdo", 1)),
    )


def test_values_are_case_sensitive_text(write_csv: WriteCsv) -> None:
    found = domain(write_csv(DATA), "Moneda", ("PYG", "USD"))
    assert (found.unexpected, found.examples) == (3, (("EUR", 2), ("usd", 1)))


def test_examples_follow_top_n_and_ties_keep_first_seen(write_csv: WriteCsv) -> None:
    assert domain(write_csv(DATA), "Moneda", ("PYG",), top_n=2).examples == (
        ("EUR", 2),
        ("USD", 1),  # USD before usd: first seen
    )
    assert domain(write_csv(DATA), "Moneda", ("PYG",), top_n=0).examples == ()
    assert domain(write_csv(DATA), "Moneda", ("PYG",), top_n=0).unexpected == 4


def test_an_allowed_list_is_stripped_and_deduplicated() -> None:
    assert allowed_list([" PYG", "USD ", "PYG"]) == ("PYG", "USD")
    for bad in ([], [""], ["PYG", " "]):
        with pytest.raises(ValueError, match="at least one value and no empty ones"):
            allowed_list(bad)


def test_profile_refuses_an_empty_list_before_reading(write_csv: WriteCsv) -> None:
    with pytest.raises(ValueError, match="at least one value"):
        profile_file(write_csv(DATA), delimiter=";", allowed_values={"Estado": []})


def test_unprofiled_and_unknown_columns_are_skipped(write_csv: WriteCsv) -> None:
    report = profile_file(
        write_csv(DATA),
        delimiter=";",
        columns=("Guía",),
        allowed_values={"Estado": STATUS, "Nada": ("x",)},
    )
    assert report.domains == ()


def test_build_report_measures_the_same(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    table = read_table(path, delimiter=";")
    built = build_report(table, na_tokens=("s/d",), allowed_values={"Estado": STATUS})
    assert built.domains == (domain(path, "Estado", STATUS),)


def test_no_lists_no_domains(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv(DATA), delimiter=";").domains == ()


# --- evaluate() ----------------------------------------------------------------


def test_evaluate_fails_and_describes(write_csv: WriteCsv) -> None:
    allowed = {"Estado": STATUS}
    report = profile_file(
        write_csv(DATA), delimiter=";", na_tokens=("s/d",), allowed_values=allowed
    )
    (check,) = evaluate(report, allowed_values=allowed)
    assert (check.check, check.column, check.limit, check.value, check.passed) == (
        CHECK_ALLOWED_VALUES,
        "Estado",
        0,
        3,
        False,
    )
    assert check.describe() == (
        "column 'Estado' has 3 cells outside the allowed values (Entregado, En tránsito, "
        'Pendiente): "Devuelto" in 2 cells, "Entregdo" in 1 cell'
    )


def test_evaluate_passes(write_csv: WriteCsv) -> None:
    allowed = {"Moneda": ("PYG", "USD", "usd", "EUR")}
    report = profile_file(write_csv(DATA), delimiter=";", allowed_values=allowed)
    (check,) = evaluate(report, allowed_values=allowed)
    assert check.passed and check.value == 0
    assert check.describe() == "column 'Moneda' has only allowed values (PYG, USD, usd, EUR)"


def test_one_cell_and_no_examples(write_csv: WriteCsv) -> None:
    allowed = {"Guía": ("A1", "A2", "A3", "A4", "A5", "A6")}
    report = profile_file(write_csv(DATA), delimiter=";", top_n=0, allowed_values=allowed)
    (check,) = evaluate(report, allowed_values=allowed)
    assert check.describe() == (
        "column 'Guía' has 1 cell outside the allowed values (A1, A2, A3, A4, A5, A6)"
    )


def test_a_long_list_is_shortened_in_the_message(write_csv: WriteCsv) -> None:
    allowed = {"Moneda": tuple(f"C{i}" for i in range(12))}
    report = profile_file(write_csv(DATA), delimiter=";", top_n=0, allowed_values=allowed)
    (check,) = evaluate(report, allowed_values=allowed)
    assert check.describe() == (
        "column 'Moneda' has 7 cells outside the allowed values "
        "(C0, C1, C2, C3, C4, C5, C6, C7, C8, C9, ... (12 values))"
    )


def test_evaluate_needs_the_same_list_in_the_report(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    report = profile_file(path, delimiter=";", allowed_values={"Estado": STATUS})
    with pytest.raises(ValueError, match="'Estado' has an allowed_values check but the report"):
        evaluate(report, allowed_values={"Estado": ("Entregado",)})
    with pytest.raises(ValueError, match="'Moneda' has an allowed_values check"):
        evaluate(report, allowed_values={"Moneda": ("PYG",)})
    # The same list, written differently, matches.
    assert evaluate(report, allowed_values={"Estado": [" Entregado", "En tránsito", "Pendiente"]})


def test_unknown_and_unprofiled_columns(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    report = profile_file(path, delimiter=";")
    checks = evaluate(report, allowed_values={"Estad": ("x",)})
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "Estad", False)
    ]
    narrow = profile_file(path, delimiter=";", columns=("Guía",))
    with pytest.raises(ValueError, match="column 'Estado' has a per-column check"):
        evaluate(narrow, allowed_values={"Estado": STATUS})


# --- command line --------------------------------------------------------------


def run(write_csv: WriteCsv, *args: str) -> int:
    return main([str(write_csv(DATA)), "--delimiter", "auto", "--na", "s/d", *args])


def test_cli_fails_and_the_last_list_wins(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run(
        write_csv,
        "--allowed-values",
        "Estado=Entregado",
        "--allowed-values",
        "Estado=Entregado,Devuelto",
    )
    out, err = capsys.readouterr()
    assert code == 8
    assert err == (
        "check failed: column 'Estado' has 1 cell outside the allowed values "
        '(Entregado, Devuelto): "Entregdo" in 1 cell\n'
    )
    assert out.count("allowed values") == 1


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--format", "json", "--allowed-values", "Moneda=PYG,USD") == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check == {
        "check": "allowed_values",
        "column": "Moneda",
        "limit": 0,
        "value": 3,
        "passed": False,
        "allowed": ["PYG", "USD"],
        "unexpected": {"EUR": 2, "usd": 1},
    }


def test_cli_name_with_an_equals_sign(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a=b;c\nx;1\n")
    assert main([str(path), "--delimiter", ";", "--allowed-values", "a=b=x"]) == 0
    assert "column 'a=b' has only allowed values (x)" in capsys.readouterr().out


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json") == 0
    out = capsys.readouterr().out
    assert "allowed" not in out and "unexpected" not in out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--allowed-values", "Estado"], "invalid --allowed-values value: 'Estado' (use NAME="),
        (["--allowed-values", "=PYG"], "invalid --allowed-values value: '=PYG' (use NAME="),
        (["--allowed-values", "Moneda="], "every value must be non-empty"),
        (["--allowed-values", "Moneda=PYG,,USD"], "every value must be non-empty"),
        (["--columns", "Guía", "--allowed-values", "Estado=x"], "--allowed-values checks column"),
    ],
)
def test_cli_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(write_csv, *args)
    assert exc.value.code == 2
    assert message in capsys.readouterr().err
