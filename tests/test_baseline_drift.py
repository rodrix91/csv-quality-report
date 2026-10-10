"""Tests for the drift gates ``--max-row-drop`` and ``--max-missing-increase`` (issue #101)."""

from __future__ import annotations

import json
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report import Comparison, compare_reports
from csv_quality_report.checks import (
    CHECK_MISSING_INCREASE,
    CHECK_ROW_DROP,
    missing_increase_checks,
    row_drop_check,
)
from csv_quality_report.cli import main
from csv_quality_report.compare import MissingCount
from csv_quality_report.profile import profile_file
from csv_quality_report.render import render_json

WriteCsv = Callable[..., Path]
BEFORE = "id,peso,nota\n1,3,a\n2,4,b\n3,5,c\n4,6,d\n"
AFTER = "id,peso,moneda\n1,,PYG\n2,,PYG\n3,5,PYG\n"


def rows(count: int, missing: int = 0) -> str:
    """A two-column CSV with ``count`` rows, the first ``missing`` without a value."""
    lines = [f"{i},{'' if i < missing else i}" for i in range(count)]
    return "id,valor\n" + "\n".join(lines) + "\n"


def baseline_of(write_csv: WriteCsv, text: str = BEFORE) -> dict[str, Any]:
    path = write_csv(text, "before.csv")
    data: dict[str, Any] = json.loads(render_json(profile_file(path), str(path)))
    return data


def write_baseline(write_csv: WriteCsv, tmp_path: Path, text: str = BEFORE) -> str:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(baseline_of(write_csv, text)), encoding="utf-8")
    return str(path)


def comparison(before: int, after: int, *counts: MissingCount) -> Comparison:
    return Comparison("x.csv", before, after, (), (), (), (), counts)


def test_missing_counts_cover_the_columns_in_both_reports(write_csv: WriteCsv) -> None:
    result = compare_reports(baseline_of(write_csv), profile_file(write_csv(AFTER)))
    # 'nota' was removed and 'moneda' added: neither is compared.
    assert result.missing_counts == (MissingCount("id", 0, 0), MissingCount("peso", 0, 2))
    selected = profile_file(write_csv(AFTER), columns=["peso"])
    assert compare_reports(baseline_of(write_csv), selected).missing_counts == (
        MissingCount("peso", 0, 2),
    )


@pytest.mark.parametrize("missing", [None, "2", True, -1, 1.0])
def test_baseline_without_a_valid_count(write_csv: WriteCsv, missing: object) -> None:
    baseline = baseline_of(write_csv)
    entry = baseline["columns"][1]
    if missing is None:
        del entry["missing"]
    else:
        entry["missing"] = missing
    result = compare_reports(baseline, profile_file(write_csv(AFTER)))
    assert result.missing_counts[1] == MissingCount("peso", None, 2)
    [_, check] = missing_increase_checks(result, 100)
    assert (check.passed, check.value) == (False, 0)
    assert check.describe() == (
        "column 'peso' cannot be compared with the baseline "
        "(the baseline has no 'missing' count for it)"
    )


def test_old_comparisons_have_no_counts() -> None:
    # Comparison gained missing_counts with a default: older code keeps working.
    old = Comparison("x.csv", 1, 1, (), (), (), ())
    assert old.missing_counts == ()
    assert missing_increase_checks(old, 0) == []


@pytest.mark.parametrize(
    ("before", "after", "limit", "value", "passed", "message"),
    [
        (10, 5, 50, 50, True, "row count fell 50% since the baseline (10 -> 5 rows; limit 50%)"),
        (
            10,
            5,
            49.9,
            50,
            False,
            "row count fell 50% since the baseline (10 -> 5 rows; limit 49.9%)",
        ),
        (
            3,
            2,
            33.3333,
            33.3333,
            False,
            "row count fell 33.33% since the baseline (3 -> 2 rows; limit 33.33%)",
        ),
        (8, 9, 0, 0, True, "row count did not fall since the baseline (8 -> 9 rows; limit 0%)"),
        (8, 8, 0, 0, True, "row count did not fall since the baseline (8 -> 8 rows; limit 0%)"),
        (0, 0, 0, 0, True, "row count did not fall since the baseline (0 -> 0 rows; limit 0%)"),
        (4, 0, 99, 100, False, "row count fell 100% since the baseline (4 -> 0 rows; limit 99%)"),
    ],
)
def test_row_drop_check(
    before: int, after: int, limit: float, value: float, passed: bool, message: str
) -> None:
    check = row_drop_check(comparison(before, after), limit)
    assert (check.check, check.column, check.limit) == (CHECK_ROW_DROP, None, limit)
    assert (check.value, check.passed) == (value, passed)
    assert check.describe() == message


def test_row_drop_limit_is_the_decimal_written() -> None:
    # 7 rows less of 1000 is exactly 0.7 %, equal to the limit: it passes,
    # although the binary float 0.7 is slightly below 7/10.
    assert Fraction(0.7) < Fraction(7, 10)
    assert row_drop_check(comparison(1000, 993), 0.7).passed
    assert not row_drop_check(comparison(1000, 992), 0.7).passed


def test_missing_increase_checks() -> None:
    counts = (
        MissingCount("a", 1, 4),  # 12.5% -> 44.44%: +31.94 points
        MissingCount("b", 2, 2),  # 25% -> 22.22%: fell
        MissingCount("c", 0, 0),
    )
    a, b, c = missing_increase_checks(comparison(8, 9, *counts), 20)
    assert (a.check, a.column, a.limit, a.value, a.passed) == (
        CHECK_MISSING_INCREASE,
        "a",
        20,
        31.9444,
        False,
    )
    assert a.describe() == (
        "column 'a' missing values rose 31.94 points since the baseline "
        "(12.5% -> 44.44%; limit 20 points)"
    )
    assert (b.value, b.passed) == (-2.7778, True)
    assert b.describe() == (
        "column 'b' missing values did not rise since the baseline (25% -> 22.22%; limit 20 points)"
    )
    assert (c.value, c.passed) == (0, True)
    assert c.describe() == (
        "column 'c' missing values did not rise since the baseline (0% -> 0%; limit 20 points)"
    )


def test_missing_increase_is_exact() -> None:
    # 1 of 7 (14.29%) -> 9 of 14 (64.29%) rises exactly 50 points; in binary
    # floats 100 * 9 / 14 - 100 * 1 / 7 is just above 50.
    assert 100 * 9 / 14 - 100 * 1 / 7 > 50
    [check] = missing_increase_checks(comparison(7, 14, MissingCount("a", 1, 9)), 50)
    assert (check.value, check.passed) == (50, True)
    [above] = missing_increase_checks(comparison(7, 14, MissingCount("a", 1, 10)), 50)
    assert not above.passed


def test_tiny_rise_is_not_shown_as_zero() -> None:
    # One more missing cell in three million rows: 0.0000333 points, which
    # four decimals would show as 0 next to a failed limit of 0.
    [check] = missing_increase_checks(comparison(3_000_000, 3_000_000, MissingCount("a", 0, 1)), 0)
    assert not check.passed and 0 < check.value < 0.0001
    assert check.describe().startswith("column 'a' missing values rose 3.333e-05 points")


def test_empty_files_have_no_missing_share() -> None:
    [check] = missing_increase_checks(comparison(0, 0, MissingCount("a", 0, 0)), 0)
    assert (check.value, check.passed) == (0, True)


def test_cli_truncated_export_fails(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path, rows(10))
    today = str(write_csv(rows(4)))
    assert main([today, "--baseline", baseline, "--max-row-drop", "60"]) == 0
    capsys.readouterr()
    assert main([today, "--baseline", baseline, "--max-row-drop", "50"]) == 8
    captured = capsys.readouterr()
    assert captured.err == (
        "check failed: row count fell 60% since the baseline (10 -> 4 rows; limit 50%)\n"
    )
    assert "- FAIL: row count fell 60% since the baseline" in captured.out


def test_cli_emptied_column_fails(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    args = [str(write_csv(AFTER)), "--baseline", baseline, "--format", "json"]
    assert main([*args, "--max-missing-increase", "50"]) == 8
    data = json.loads(capsys.readouterr().out)
    assert data["checks"] == [
        {"check": "missing_increase", "column": "id", "limit": 50, "value": 0, "passed": True},
        {
            "check": "missing_increase",
            "column": "peso",
            "limit": 50,
            "value": 66.6667,
            "passed": False,
        },
    ]
    assert main([*args, "--max-missing-increase", "70"]) == 0


def test_cli_all_baseline_gates_together(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    args = [str(write_csv(AFTER)), "--baseline", baseline, "--format", "json"]
    gates = ["--fail-on-schema-change", "--max-row-drop", "10", "--max-missing-increase", "10"]
    assert main([*args, *gates]) == 8
    checks = json.loads(capsys.readouterr().out)["checks"]
    assert [(c["check"], c["column"], c["passed"]) for c in checks] == [
        ("schema_change", None, False),
        ("row_drop", None, False),
        ("missing_increase", "id", True),
        ("missing_increase", "peso", False),
    ]


@pytest.mark.parametrize("option", ["--max-row-drop", "--max-missing-increase"])
def test_drift_gates_need_a_baseline(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], option: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(BEFORE)), option, "5"])
    assert excinfo.value.code == 2
    assert f"{option} needs --baseline" in capsys.readouterr().err


@pytest.mark.parametrize("option", ["--max-row-drop", "--max-missing-increase"])
@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("abc", "invalid percentage: 'abc'"),
        ("-1", "between 0 and 100"),
        ("100.5", "between 0 and 100"),
        ("nan", "between 0 and 100"),
    ],
)
def test_drift_gates_reject_bad_percentages(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    option: str,
    value: str,
    message: str,
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(BEFORE)), "--baseline", baseline, option, value])
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err
