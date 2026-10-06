"""Tests for the ``--max-affixes`` quality gate (issue #75)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.checks import CHECK_MAX_AFFIXES, CHECK_REQUIRED_COLUMN, evaluate
from csv_quality_report.cli import main
from csv_quality_report.profile import profile_file

WriteCsv = Callable[..., Path]
DATA = "monto;peso;id\nGs. 150.000;12 kg;1\nUS$ 25;3 lb;2\nGs. 89.500;45 kg;3\n150;8 kg;4\n"
AFFIXES = ("Gs.", "US$", "kg", "lb")
OPTIONS = ["--delimiter", ";", "--decimal-comma", "--thousands", "dot"]
for _affix in AFFIXES:
    OPTIONS += ["--number-affix", _affix]


def checks_json(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, list[dict[str, Any]]]:
    code = main([*args, "--format", "json"])
    checks: list[dict[str, Any]] = json.loads(capsys.readouterr().out)["checks"]
    return code, checks


def test_mixed_currencies_fail(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code, checks = checks_json(capsys, str(write_csv(DATA)), *OPTIONS, "--max-affixes", "monto=1")
    assert code == 8
    assert checks == [
        {
            "check": "max_affixes",
            "column": "monto",
            "limit": 1,
            "value": 2,
            "passed": False,
            "found": {"Gs.": 2, "US$": 1},
        }
    ]


def test_messages(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    args = [str(write_csv(DATA)), *OPTIONS, "--max-affixes", "monto=1", "--max-affixes", "peso=2"]
    assert main([*args, "--max-affixes", "id=0"]) == 8
    captured = capsys.readouterr()
    assert captured.err == (
        "check failed: column 'monto' mixes 2 number affixes: "
        '"Gs." in 2 cells, "US$" in 1 cell (limit 1)\n'
    )
    assert (
        '- pass: column \'peso\' mixes 2 number affixes: "kg" in 3 cells, "lb" in 1 cell '
        "(limit 2)\n" in captured.out
    )
    assert "- pass: column 'id' has 0 number affixes (limit 0)\n" in captured.out


def test_one_affix_passes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv("monto\n$ 5\n$ 7\n9\n")
    assert main([str(path), "--number-affix", "$", "--max-affixes", "monto=1"]) == 0
    assert "- pass: column 'monto' has 1 number affix: \"$\" in 2 cells (limit 1)\n" in (
        capsys.readouterr().out
    )


def test_limit_zero_rejects_any_affix(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("p\n5\n$ 7\n"), number_affixes=("$",))
    (check,) = evaluate(report, column_max_affixes={"p": 0})
    assert (check.check, check.value, check.passed) == (CHECK_MAX_AFFIXES, 1, False)


def test_unknown_column_is_a_missing_required_column(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA), delimiter=";", number_affixes=AFFIXES)
    (check,) = evaluate(report, column_max_affixes={"Monto": 1})
    assert (check.check, check.column, check.passed, check.hint) == (
        CHECK_REQUIRED_COLUMN,
        "Monto",
        False,
        "",
    )


def test_needs_number_affixes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    report = profile_file(write_csv(DATA), delimiter=";")
    with pytest.raises(ValueError, match="need a report built with number affixes"):
        evaluate(report, column_max_affixes={"monto": 1})
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(DATA)), "--max-affixes", "monto=1"])
    assert excinfo.value.code == 2
    assert "--max-affixes needs --number-affix" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("monto", "invalid --max-affixes value: 'monto' (use NAME=N)"),
        ("=1", "invalid --max-affixes value: '=1' (use NAME=N)"),
        ("monto=-1", "invalid --max-affixes value: 'monto=-1' (must be >= 0)"),
        ("monto=x", "invalid --max-affixes value: 'monto=x' (invalid integer: 'x')"),
    ],
)
def test_invalid_values_are_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], value: str, message: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(DATA)), "--number-affix", "$", "--max-affixes", value])
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err


def test_names_may_contain_equals_and_last_limit_wins(write_csv: WriteCsv) -> None:
    path = write_csv("a=b\n$ 1\nUS$ 2\n")
    args = [str(path), "--number-affix", "$", "--number-affix", "US$"]
    assert main([*args, "--max-affixes", "a=b=1"]) == 8
    assert main([*args, "--max-affixes", "a=b=1", "--max-affixes", "a=b=2"]) == 0


def test_other_checks_keep_their_json_shape(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    _, checks = checks_json(
        capsys, str(write_csv(DATA)), *OPTIONS, "--max-duplicates", "0", "--max-affixes", "peso=2"
    )
    assert "found" not in checks[0]
    assert checks[1]["found"] == {"kg": 3, "lb": 1}
