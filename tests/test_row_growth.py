"""Tests for the drift gate ``--max-row-growth`` (issue #216)."""

from __future__ import annotations

import json
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import pytest

from csv_quality_report import Comparison
from csv_quality_report.checks import CHECK_ROW_GROWTH, row_growth_check
from csv_quality_report.cli import main
from csv_quality_report.profile import profile_file
from csv_quality_report.render import render_json

WriteCsv = Callable[..., Path]


def rows(count: int) -> str:
    return "id,valor\n" + "".join(f"{i},{i * 10}\n" for i in range(count))


def comparison(before: int, after: int) -> Comparison:
    return Comparison("x.csv", before, after, (), (), (), (), ())


def write_baseline(write_csv: WriteCsv, tmp_path: Path, count: int) -> str:
    source = write_csv(rows(count), "before.csv")
    path = tmp_path / "baseline.json"
    path.write_text(render_json(profile_file(source), str(source)), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize(
    ("before", "after", "limit", "value", "passed", "message"),
    [
        (
            10,
            20,
            50,
            100,
            False,
            "row count rose 100% since the baseline (10 -> 20 rows; limit 50%)",
        ),
        (
            10,
            20,
            100,
            100,
            True,
            "row count rose 100% since the baseline (10 -> 20 rows; limit 100%)",
        ),
        (
            10,
            35,
            200,
            250,
            False,
            "row count rose 250% since the baseline (10 -> 35 rows; limit 200%)",
        ),
        (
            3,
            4,
            33.34,
            33.3333,
            True,
            "row count rose 33.33% since the baseline (3 -> 4 rows; limit 33.34%)",
        ),
        (8, 7, 0, 0, True, "row count did not rise since the baseline (8 -> 7 rows; limit 0%)"),
        (8, 8, 0, 0, True, "row count did not rise since the baseline (8 -> 8 rows; limit 0%)"),
        (0, 0, 0, 0, True, "row count did not rise since the baseline (0 -> 0 rows; limit 0%)"),
        (
            0,
            5,
            0,
            0,
            True,
            "row count rose since the baseline, which had no rows, so the growth cannot be "
            "measured (0 -> 5 rows; limit 0%)",
        ),
    ],
)
def test_row_growth_check(
    before: int, after: int, limit: float, value: float, passed: bool, message: str
) -> None:
    check = row_growth_check(comparison(before, after), limit)
    assert (check.check, check.column, check.limit) == (CHECK_ROW_GROWTH, None, limit)
    assert (check.value, check.passed) == (value, passed)
    assert check.describe() == message


def test_row_growth_limit_is_the_decimal_written() -> None:
    # 7 rows more than 1000 is exactly 0.7 %, equal to the limit: it passes,
    # although the binary float 0.7 is slightly below 7/10.
    assert Fraction(0.7) < Fraction(7, 10)
    assert row_growth_check(comparison(1000, 1007), 0.7).passed
    assert not row_growth_check(comparison(1000, 1008), 0.7).passed


def test_tiny_growth_is_not_shown_as_zero() -> None:
    check = row_growth_check(comparison(3_000_000, 3_000_001), 0)
    assert not check.passed and 0 < check.value < 0.0001


def test_cli_doubled_export_fails(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path, 10)
    today = str(write_csv(rows(20)))
    assert main([today, "--baseline", baseline, "--max-row-growth", "100"]) == 0
    capsys.readouterr()
    assert main([today, "--baseline", baseline, "--max-row-growth", "50"]) == 8
    captured = capsys.readouterr()
    assert captured.err == (
        "check failed: row count rose 100% since the baseline (10 -> 20 rows; limit 50%)\n"
    )
    assert "- FAIL: row count rose 100% since the baseline" in captured.out


def test_cli_json_and_both_row_gates(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path, 10)
    args = [str(write_csv(rows(12))), "--baseline", baseline, "--format", "json"]
    gates = ["--max-row-drop", "10", "--max-row-growth", "10"]
    assert main([*args, *gates]) == 8
    checks = json.loads(capsys.readouterr().out)["checks"]
    assert checks == [
        {"check": "row_drop", "column": None, "limit": 10, "value": 0, "passed": True},
        {"check": "row_growth", "column": None, "limit": 10, "value": 20, "passed": False},
    ]


def test_cli_without_the_option_has_no_row_growth_check(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path, 10)
    args = [str(write_csv(rows(30))), "--baseline", baseline, "--format", "json"]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["checks"] == []


def test_row_growth_needs_a_baseline(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(rows(3))), "--max-row-growth", "5"])
    assert excinfo.value.code == 2
    assert "--max-row-growth needs --baseline" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("abc", "invalid percentage: 'abc'"),
        ("", "invalid percentage: ''"),
        ("-1", "must be a finite number of 0 or more"),
        ("-0.001", "must be a finite number of 0 or more"),
        ("nan", "must be a finite number of 0 or more"),
        ("inf", "must be a finite number of 0 or more"),
        ("1e400", "must be a finite number of 0 or more"),
    ],
)
def test_row_growth_rejects_bad_percentages(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    value: str,
    message: str,
) -> None:
    baseline = write_baseline(write_csv, tmp_path, 3)
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(rows(3))), "--baseline", baseline, f"--max-row-growth={value}"])
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err


def test_row_growth_accepts_more_than_100(write_csv: WriteCsv, tmp_path: Path) -> None:
    baseline = write_baseline(write_csv, tmp_path, 4)
    today = str(write_csv(rows(12)))
    assert main([today, "--baseline", baseline, "--max-row-growth", "200"]) == 0
    assert main([today, "--baseline", baseline, "--max-row-growth", "199.99"]) == 8
