"""Tests for the --require-type quality gate (issue #45)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.checks import CHECK_COLUMN_TYPE, COLUMN_TYPES, evaluate
from csv_quality_report.cli import main
from csv_quality_report.errors import EXIT_CHECKS
from csv_quality_report.profile import profile_file

WriteCsv = Callable[..., Path]
TYPED = (
    "i,f,b,d,t,s,e\n1,1.5,true,2026-01-01,2026-01-01T10:00,x,\n2,2,false,2026-01-02,2026-01-02,y,\n"
)


def run(
    path: Path, capsys: pytest.CaptureFixture[str], *extra: str
) -> tuple[int, list[dict[str, Any]], str]:
    code = main([str(path), "--format", "json", *extra])
    captured = capsys.readouterr()
    checks: list[dict[str, Any]] = json.loads(captured.out)["checks"]
    return code, checks, captured.err


@pytest.mark.parametrize(
    ("column", "required", "ok"),
    [
        ("i", "int", True),
        ("i", "float", True),  # int columns satisfy float
        ("f", "float", True),
        ("f", "int", False),
        ("b", "bool", True),
        ("b", "int", False),
        ("d", "date", True),
        ("d", "datetime", True),  # date columns satisfy datetime
        ("t", "datetime", True),
        ("t", "date", False),
        ("s", "string", True),
        ("i", "string", True),  # every column satisfies string
        ("s", "int", False),
        ("e", "int", True),  # no values: nothing contradicts the type
    ],
)
def test_type_compatibility(write_csv: WriteCsv, column: str, required: str, ok: bool) -> None:
    report = profile_file(write_csv(TYPED))
    [result] = evaluate(report, column_types={column: required})
    assert (result.check, result.passed, result.expected) == (CHECK_COLUMN_TYPE, ok, required)


def test_json_items_add_expected_and_actual(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, checks, _ = run(write_csv(TYPED), capsys, "--require-type", "f=int")
    assert code == EXIT_CHECKS
    assert checks == [
        {
            "check": "column_type",
            "column": "f",
            "limit": 1,
            "value": 0,
            "passed": False,
            "expected": "int",
            "actual": "float",
        }
    ]


def test_failure_names_stray_values_from_the_type_hint(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    data = "qty\n" + "".join(f"{i}\n" for i in range(30)) + "N/A\nN/A\n12a\n"
    code, _, err = run(write_csv(data), capsys, "--require-type", "qty=int")
    assert code == EXIT_CHECKS
    assert err == (
        'check failed: column \'qty\' is string, expected int (3 values do not fit: "N/A", "12a")\n'
    )


def test_hint_of_an_incompatible_type_is_not_used(write_csv: WriteCsv) -> None:
    data = "d\n" + "".join(f"2026-01-{i:02d}\n" for i in range(1, 29)) + "x\n"
    [result] = evaluate(profile_file(write_csv(data)), column_types={"d": "int"})
    assert result.describe() == "column 'd' is string, expected int"


def test_passing_check_description(write_csv: WriteCsv) -> None:
    [result] = evaluate(profile_file(write_csv(TYPED)), column_types={"i": "float"})
    assert result.describe() == "column 'i' is int, as required (float)"


def test_unknown_column_fails_as_required_with_hint(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, checks, err = run(write_csv(" qty\n1\n"), capsys, "--require-type", "qty=int")
    assert code == EXIT_CHECKS
    assert [c["check"] for c in checks] == ["required_column"]
    assert err.rstrip().endswith("did you mean ' qty'?")


def test_last_type_for_a_name_wins(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code, checks, _ = run(
        write_csv(TYPED), capsys, "--require-type", "f=int", "--require-type", "f=float"
    )
    assert code == 0 and checks[0]["expected"] == "float"


def test_other_check_items_keep_their_keys(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    _, checks, _ = run(write_csv(TYPED), capsys, "--max-duplicates", "0")
    assert set(checks[0]) == {"check", "column", "limit", "value", "passed"}


def test_markdown_section(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(write_csv(TYPED)), "--require-type", "s=int"]) == EXIT_CHECKS
    assert "- FAIL: column 's' is string, expected int\n" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("qty", "use NAME=TYPE"),
        ("=int", "use NAME=TYPE"),
        ("qty=integer", "use one of " + ", ".join(COLUMN_TYPES)),
        ("qty=", "invalid type"),
    ],
)
def test_invalid_values_are_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], value: str, message: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(TYPED)), f"--require-type={value}"])
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err
