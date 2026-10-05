"""Tests for per-column missing limits, --max-missing-column NAME=PCT (issue #32)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.checks import CHECK_MAX_MISSING, CHECK_REQUIRED_COLUMN, evaluate
from csv_quality_report.cli import main
from csv_quality_report.errors import EXIT_CHECKS
from csv_quality_report.profile import profile_file

WriteCsv = Callable[..., Path]
# 4 rows: id 0% missing, phone 75% missing, note 50% missing.
DATA = "id,phone,note\n1,,x\n2,,\n3,555,y\n4,,\n"


def run(
    path: Path, capsys: pytest.CaptureFixture[str], *extra: str
) -> tuple[int, list[dict[str, Any]], str]:
    code = main([str(path), "--format", "json", *extra])
    captured = capsys.readouterr()
    checks: list[dict[str, Any]] = json.loads(captured.out)["checks"]
    return code, checks, captured.err


def limits(checks: list[dict[str, Any]]) -> dict[str, tuple[float, bool]]:
    return {c["column"]: (c["limit"], c["passed"]) for c in checks if c["check"] == "max_missing"}


def test_column_limit_overrides_the_global_limit(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, checks, err = run(
        write_csv(DATA),
        capsys,
        "--max-missing",
        "10",
        "--max-missing-column",
        "phone=80",
        "--max-missing-column",
        "note=50",
    )
    assert code == 0, err
    assert limits(checks) == {"id": (10, True), "phone": (80, True), "note": (50, True)}


def test_column_limit_alone_checks_only_that_column(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, checks, err = run(write_csv(DATA), capsys, "--max-missing-column", "id=0")
    assert code == 0
    assert limits(checks) == {"id": (0, True)}


def test_stricter_column_limit_fails(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, checks, err = run(
        write_csv(DATA), capsys, "--max-missing", "100", "--max-missing-column", "note=25"
    )
    assert code == EXIT_CHECKS
    assert limits(checks)["note"] == (25, False)
    assert err == "check failed: column 'note' has 50% missing values (limit 25%)\n"


def test_limit_for_an_unknown_column_fails_instead_of_being_ignored(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, checks, err = run(write_csv(DATA), capsys, "--max-missing-column", "phnoe=80")
    assert code == EXIT_CHECKS
    assert checks == [
        {"check": "required_column", "column": "phnoe", "limit": 1, "value": 0, "passed": False}
    ]
    assert "required column 'phnoe' is missing (columns: id, phone, note)" in err


def test_unknown_column_already_required_is_reported_once(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA))
    results = evaluate(report, required_columns=["carrier"], column_max_missing={"carrier": 5})
    assert [(r.check, r.column) for r in results] == [(CHECK_REQUIRED_COLUMN, "carrier")]


def test_the_last_limit_for_a_name_wins(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    _, checks, _ = run(
        write_csv(DATA),
        capsys,
        "--max-missing-column",
        "note=10",
        "--max-missing-column",
        "note=60",
    )
    assert limits(checks) == {"note": (60, True)}


def test_names_may_contain_equals_signs(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, checks, _ = run(write_csv('"a=b",c\n1,\n2,3\n'), capsys, "--max-missing-column", "a=b=0")
    assert code == 0
    assert limits(checks) == {"a=b": (0, True)}


def test_evaluate_without_limits_is_unchanged(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA))
    assert evaluate(report) == []
    assert [r.check for r in evaluate(report, max_missing=50)] == [CHECK_MAX_MISSING] * 3


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("phone", "use NAME=PCT"),
        ("=5", "use NAME=PCT"),
        ("phone=", "invalid percentage"),
        ("phone=abc", "invalid percentage"),
        ("phone=101", "must be between 0 and 100"),
    ],
)
def test_invalid_values_are_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], value: str, message: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(DATA)), f"--max-missing-column={value}"])
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err
