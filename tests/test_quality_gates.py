"""Tests for the --max-missing / --max-duplicates quality gates (issue #18)."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.checks import CHECK_MAX_DUPLICATES, CHECK_MAX_MISSING, evaluate
from csv_quality_report.cli import main
from csv_quality_report.errors import EXIT_CHECKS
from csv_quality_report.profile import profile_file

WriteCsv = Callable[..., Path]

# 4 rows: column a has 1 missing (25%), column b none; one duplicate row.
DATA = "a,b\n1,x\n,y\n1,x\n3,z\n"


def run(
    path: Path, capsys: pytest.CaptureFixture[str], *extra: str
) -> tuple[int, dict[str, Any], str]:
    code = main([str(path), "--format", "json", *extra])
    captured = capsys.readouterr()
    report: dict[str, Any] = json.loads(captured.out)
    return code, report, captured.err


def test_no_thresholds_means_no_checks_and_exit_zero(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, rep, err = run(write_csv(DATA), capsys)
    assert (code, rep["checks"], err) == (0, [], "")


def test_missing_threshold_fails_with_exit_8_and_still_prints_report(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, rep, err = run(write_csv(DATA), capsys, "--max-missing", "10")
    assert code == EXIT_CHECKS == 8
    assert rep["rows"] == 4  # the full report is still there
    assert rep["checks"] == [
        {"check": "max_missing", "column": "a", "limit": 10.0, "value": 25.0, "passed": False},
        {"check": "max_missing", "column": "b", "limit": 10.0, "value": 0.0, "passed": True},
    ]
    assert err == "check failed: column 'a' has 25% missing values (limit 10%)\n"


def test_value_equal_to_the_limit_passes(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, rep, _ = run(write_csv(DATA), capsys, "--max-missing", "25", "--max-duplicates", "1")
    assert code == 0
    assert all(c["passed"] for c in rep["checks"])


def test_rounding_cannot_hide_a_value_above_the_limit(write_csv: WriteCsv) -> None:
    # 1 missing of 3001 rows is 0.0333...%, shown as 0.0 in missing_pct.
    path = write_csv("a\n" + "1\n" * 3000 + "  \n")
    report = profile_file(path)
    assert report.columns[0].missing_pct == 0.0
    [result] = evaluate(report, max_missing=0.0)
    assert not result.passed
    assert result.value == pytest.approx(0.0333, abs=1e-4)


def test_duplicates_threshold(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code, rep, err = run(write_csv(DATA), capsys, "--max-duplicates", "0")
    assert code == EXIT_CHECKS
    assert rep["checks"] == [
        {"check": "max_duplicates", "column": None, "limit": 0, "value": 1, "passed": False}
    ]
    assert err == "check failed: 1 duplicate rows (limit 0)\n"


def test_both_checks_report_every_failure(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, rep, err = run(write_csv(DATA), capsys, "--max-missing", "0", "--max-duplicates", "0")
    assert code == EXIT_CHECKS
    assert [c["check"] for c in rep["checks"] if not c["passed"]] == [
        CHECK_MAX_MISSING,
        CHECK_MAX_DUPLICATES,
    ]
    assert err.count("check failed:") == 2


def test_empty_file_body_passes_missing_check(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("a,b\n"))
    assert all(r.passed and r.value == 0.0 for r in evaluate(report, max_missing=0))


def test_fractional_percentages_are_printed_readably(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, err = run(write_csv("a\n1\n\n2\n \n"), capsys, "--max-missing", "12.5")
    assert err == "check failed: column 'a' has 33.33% missing values (limit 12.5%)\n"


def test_markdown_checks_section(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv(DATA)
    assert main([str(path), "--max-missing", "10", "--max-duplicates", "5"]) == EXIT_CHECKS
    out = capsys.readouterr().out
    assert "## Checks: FAILED (1 of 3 failed)\n" in out
    assert "- FAIL: column 'a' has 25% missing values (limit 10%)\n" in out
    assert "- pass: 1 duplicate rows (limit 5)\n" in out


def test_markdown_has_no_checks_section_without_thresholds(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write_csv(DATA))]) == 0
    assert "## Checks" not in capsys.readouterr().out


def test_markdown_passed_heading(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(write_csv(DATA)), "--max-missing", "50"]) == 0
    assert "## Checks: passed (0 of 2 failed)\n" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("flag", "value", "message"),
    [
        ("--max-missing", "-1", "must be between 0 and 100"),
        ("--max-missing", "100.5", "must be between 0 and 100"),
        ("--max-missing", "ten", "invalid percentage"),
        ("--max-duplicates", "-1", "must be >= 0"),
        ("--max-duplicates", "1.5", "invalid integer"),
    ],
)
def test_invalid_threshold_values_are_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], flag: str, value: str, message: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(DATA)), f"{flag}={value}"])
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err


def test_reading_errors_keep_their_exit_codes_with_thresholds(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write_csv("a,b\n1\n")), "--max-missing", "0"]) == 6
    assert capsys.readouterr().out == ""


def test_exit_code_from_a_real_process(write_csv: WriteCsv, cli_env: dict[str, str]) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "csv_quality_report", str(write_csv(DATA)), "--max-duplicates=0"],
        env=cli_env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == EXIT_CHECKS
    assert proc.stdout.startswith("# CSV quality report:")
    assert "check failed: 1 duplicate rows" in proc.stderr
