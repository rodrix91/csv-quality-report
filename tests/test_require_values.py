"""Tests for ``--require-values NAME=V1,V2,...`` (issue #275)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import build_report, evaluate, read_table
from csv_quality_report.checks import CHECK_REQUIRED_COLUMN, CHECK_REQUIRED_VALUES
from csv_quality_report.cli import main
from csv_quality_report.profile import PresenceProfile, profile_file, required_list

WriteCsv = Callable[..., Path]
# A consolidated sales export of four branches, one of which (Tarija) did not
# upload; " El Alto " is padded, "sucre" is in lower case and "s/d" is missing.
DATA = "Sucursal;Monto\nLa Paz;100\n El Alto ;80\nLa Paz;20\nsucre;15\ns/d;5\n;7\n"
BRANCHES = ("La Paz", "El Alto", "Sucre", "Tarija")


def presence(
    path: Path, name: str, required: tuple[str, ...], **options: object
) -> PresenceProfile:
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        required_values={name: required},
        **options,  # type: ignore[arg-type]
    )
    (found,) = report.presences
    return found


# --- measuring in the profile ------------------------------------------------


def test_absent_values_are_listed_in_the_order_given(write_csv: WriteCsv) -> None:
    found = presence(write_csv(DATA), "Sucursal", BRANCHES)
    # " El Alto " counts as "El Alto"; "sucre" is not "Sucre" (case-sensitive).
    assert found == PresenceProfile(
        column="Sucursal", required=BRANCHES, absent=("Sucre", "Tarija")
    )


def test_missing_cells_never_hold_a_required_value(write_csv: WriteCsv) -> None:
    # "s/d" is a missing marker here, so it is absent although a cell holds it.
    assert presence(write_csv(DATA), "Sucursal", ("s/d", "La Paz")).absent == ("s/d",)
    # Without --na it is an ordinary value.
    report = profile_file(write_csv(DATA), delimiter=";", required_values={"Sucursal": ("s/d",)})
    assert report.presences[0].absent == ()


def test_missing_markers_in_any_case_are_not_values(write_csv: WriteCsv) -> None:
    path = write_csv(DATA.replace("s/d", "S/D"))
    found = presence(path, "Sucursal", ("S/D",), na_ignore_case=True)
    assert found.absent == ("S/D",)


def test_numbers_compare_as_text(write_csv: WriteCsv) -> None:
    assert presence(write_csv(DATA), "Monto", ("100", "100.0", "7")).absent == ("100.0",)


def test_a_value_seen_only_in_a_later_batch_is_found(write_csv: WriteCsv) -> None:
    rows = "".join(f"La Paz;{i}\n" for i in range(25_000))
    path = write_csv("Sucursal;Monto\n" + rows + "Tarija;1\n")
    assert presence(path, "Sucursal", ("La Paz", "Tarija")).absent == ()
    assert presence(path, "Sucursal", ("Tarija",), max_rows=25_000).absent == ("Tarija",)


def test_a_required_list_is_stripped_and_deduplicated() -> None:
    assert required_list([" La Paz", "Sucre ", "La Paz"]) == ("La Paz", "Sucre")
    for bad in ([], [""], ["La Paz", " "]):
        with pytest.raises(ValueError, match="at least one value and no empty ones"):
            required_list(bad)


def test_profile_refuses_an_empty_list_before_reading(write_csv: WriteCsv) -> None:
    with pytest.raises(ValueError, match="required-values list needs at least one value"):
        profile_file(write_csv(DATA), delimiter=";", required_values={"Sucursal": []})


def test_unprofiled_and_unknown_columns_are_skipped(write_csv: WriteCsv) -> None:
    report = profile_file(
        write_csv(DATA),
        delimiter=";",
        columns=("Monto",),
        required_values={"Sucursal": BRANCHES, "Nada": ("x",)},
    )
    assert report.presences == ()


def test_build_report_measures_the_same(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    table = read_table(path, delimiter=";")
    built = build_report(table, na_tokens=("s/d",), required_values={"Sucursal": BRANCHES})
    assert built.presences == (presence(path, "Sucursal", BRANCHES),)


def test_no_lists_no_presences(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv(DATA), delimiter=";").presences == ()


# --- evaluate() ----------------------------------------------------------------


def test_evaluate_fails_and_describes(write_csv: WriteCsv) -> None:
    report = profile_file(
        write_csv(DATA),
        delimiter=";",
        na_tokens=("s/d",),
        required_values={"Sucursal": BRANCHES},
    )
    (check,) = evaluate(report, required_values={"Sucursal": BRANCHES})
    assert (check.check, check.column, check.limit, check.value, check.passed) == (
        CHECK_REQUIRED_VALUES,
        "Sucursal",
        0,
        2,
        False,
    )
    assert (check.required, check.absent) == (BRANCHES, ("Sucre", "Tarija"))
    assert check.describe() == (
        'column \'Sucursal\' lacks 2 of 4 required values: "Sucre", "Tarija"'
    )


def test_evaluate_passes(write_csv: WriteCsv) -> None:
    required = {"Sucursal": ("La Paz", "El Alto", "sucre")}
    report = profile_file(write_csv(DATA), delimiter=";", required_values=required)
    (check,) = evaluate(report, required_values=required)
    assert check.passed and check.value == 0
    assert check.describe() == (
        "column 'Sucursal' has all 3 required values (La Paz, El Alto, sucre)"
    )


def test_one_required_value(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    for value, text in [
        ("La Paz", "column 'Sucursal' has the required value (La Paz)"),
        ("Tarija", "column 'Sucursal' lacks 1 of 1 required value: \"Tarija\""),
    ]:
        report = profile_file(path, delimiter=";", required_values={"Sucursal": (value,)})
        (check,) = evaluate(report, required_values={"Sucursal": (value,)})
        assert check.describe() == text


def test_long_lists_are_shortened_in_the_message(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    absent = {"Sucursal": tuple(f"S{i}" for i in range(12))}
    report = profile_file(path, delimiter=";", required_values=absent)
    (check,) = evaluate(report, required_values=absent)
    assert check.value == 12
    assert check.describe() == (
        "column 'Sucursal' lacks 12 of 12 required values: "
        '"S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", ... (12 values)'
    )
    values = tuple(str(i) for i in range(12))
    path = write_csv("N\n" + "".join(f"{v}\n" for v in values))
    report = profile_file(path, required_values={"N": values})
    (check,) = evaluate(report, required_values={"N": values})
    assert check.describe() == (
        "column 'N' has all 12 required values (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, ...)"
    )


def test_evaluate_needs_the_same_list_in_the_report(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    report = profile_file(path, delimiter=";", required_values={"Sucursal": BRANCHES})
    with pytest.raises(ValueError, match="'Sucursal' has a required_values check but the report"):
        evaluate(report, required_values={"Sucursal": ("La Paz",)})
    with pytest.raises(ValueError, match="'Monto' has a required_values check"):
        evaluate(report, required_values={"Monto": ("100",)})
    with pytest.raises(ValueError, match="at least one value and no empty ones"):
        evaluate(report, required_values={"Sucursal": ("La Paz", "")})
    # The same list, written differently, matches.
    assert evaluate(
        report, required_values={"Sucursal": [" La Paz", "El Alto", "Sucre", "Tarija", "Sucre"]}
    )


def test_unknown_and_unprofiled_columns(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    report = profile_file(path, delimiter=";")
    checks = evaluate(report, required_values={"Sucursl": ("x",)})
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "Sucursl", False)
    ]
    narrow = profile_file(path, delimiter=";", columns=("Monto",))
    with pytest.raises(ValueError, match="column 'Sucursal' has a per-column check"):
        evaluate(narrow, required_values={"Sucursal": BRANCHES})


# --- command line --------------------------------------------------------------


def run(write_csv: WriteCsv, *args: str) -> int:
    return main([str(write_csv(DATA)), "--delimiter", "auto", "--na", "s/d", *args])


def test_cli_fails_and_the_last_list_wins(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run(
        write_csv,
        "--require-values",
        "Sucursal=Potosí",
        "--require-values",
        "Sucursal=La Paz,El Alto,Tarija",
    )
    out, err = capsys.readouterr()
    assert code == 8
    assert err == ("check failed: column 'Sucursal' lacks 1 of 3 required values: \"Tarija\"\n")
    assert "Potosí" not in out


def test_cli_passes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--require-values", "Sucursal=La Paz, El Alto") == 0
    assert (
        "- pass: column 'Sucursal' has all 2 required values (La Paz, El Alto)"
        in capsys.readouterr().out
    )


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--format", "json", "--require-values", "Sucursal=Sucre,La Paz") == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check == {
        "check": "required_values",
        "column": "Sucursal",
        "limit": 0,
        "value": 1,
        "passed": False,
        "required": ["Sucre", "La Paz"],
        "absent": ["Sucre"],
    }


def test_cli_name_with_an_equals_sign(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a=b;c\nx;1\n")
    assert main([str(path), "--delimiter", ";", "--require-values", "a=b=x"]) == 0
    assert "column 'a=b' has the required value (x)" in capsys.readouterr().out


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json") == 0
    out = capsys.readouterr().out
    assert "required" not in out and "absent" not in out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--require-values", "Sucursal"], "invalid --require-values value: 'Sucursal' (use NAME="),
        (["--require-values", "=La Paz"], "invalid --require-values value: '=La Paz' (use NAME="),
        (["--require-values", "Sucursal="], "every value must be non-empty"),
        (["--require-values", "Sucursal=La Paz,,Sucre"], "every value must be non-empty"),
        (["--require-values", "Sucursal= , "], "every value must be non-empty"),
        (
            ["--columns", "Monto", "--require-values", "Sucursal=x"],
            "--require-values checks column",
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
    assert run(write_csv, "--require-values", "Sucursl=La Paz") == 8
    assert "required column 'Sucursl' is missing" in capsys.readouterr().err
