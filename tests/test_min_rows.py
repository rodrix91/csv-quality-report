"""Tests for the ``--min-rows N`` quality gate (issue #148)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import evaluate
from csv_quality_report.checks import CHECK_MIN_ROWS
from csv_quality_report.cli import main
from csv_quality_report.profile import profile_file

WriteCsv = Callable[..., Path]
HEADER_ONLY = "Remito;Despacho\r\n"
THREE_ROWS = "id,peso\n1,3\n2,4\n3,5\n"


def test_a_header_only_file_passes_the_other_gates_and_fails_min_rows(
    write_csv: WriteCsv,
) -> None:
    report = profile_file(write_csv(HEADER_ONLY), delimiter="auto")
    assert report.rows == 0
    others = evaluate(report, max_missing=0, max_duplicates=0, required_columns=["Remito"])
    assert others and all(c.passed for c in others)  # the gap this gate closes
    (check,) = evaluate(report, min_rows=1)
    assert (check.check, check.column, check.limit, check.value, check.passed) == (
        CHECK_MIN_ROWS,
        None,
        1,
        0,
        False,
    )
    assert check.describe() == "the file has 0 data rows (at least 1 required)"


def test_the_limit_is_inclusive(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(THREE_ROWS))
    assert [c.passed for c in evaluate(report, min_rows=3)] == [True]
    (failed,) = evaluate(report, min_rows=4)
    assert not failed.passed
    assert failed.describe() == "the file has 3 data rows (at least 4 required)"


def test_one_row_is_singular(write_csv: WriteCsv) -> None:
    (check,) = evaluate(profile_file(write_csv("id\n1\n")), min_rows=2)
    assert check.describe() == "the file has 1 data row (at least 2 required)"


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "3"])
def test_evaluate_refuses_a_bad_limit(write_csv: WriteCsv, value: object) -> None:
    report = profile_file(write_csv(THREE_ROWS))
    with pytest.raises(ValueError, match="min_rows must be a whole number of at least 1"):
        evaluate(report, min_rows=value)  # type: ignore[arg-type]


def test_no_check_without_the_option(write_csv: WriteCsv) -> None:
    assert evaluate(profile_file(write_csv(HEADER_ONLY))) == []


def test_cli_fails_a_header_only_export(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([str(write_csv(HEADER_ONLY)), "--delimiter", "auto", "--min-rows", "1"])
    out, err = capsys.readouterr()
    assert code == 8
    assert "- FAIL: the file has 0 data rows (at least 1 required)" in out
    assert err == "check failed: the file has 0 data rows (at least 1 required)\n"


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(write_csv(THREE_ROWS)), "--format", "json", "--min-rows", "2"]) == 0
    checks = json.loads(capsys.readouterr().out)["checks"]
    assert checks == [{"check": "min_rows", "column": None, "limit": 2, "value": 3, "passed": True}]


def test_cli_truncated_file_with_enough_rows_passes(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # --max-rows 2 reads 2 of the 3 rows: the file has at least that many.
    path = str(write_csv(THREE_ROWS))
    assert main([path, "--max-rows", "2", "--min-rows", "2"]) == 0
    assert "- pass: the file has 2 data rows (at least 2 required)" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--min-rows", "0"], "argument --min-rows: must be >= 1"),
        (["--min-rows", "-3"], "argument --min-rows: must be >= 1"),
        (["--min-rows", "dos"], "argument --min-rows: invalid integer: 'dos'"),
        (
            ["--min-rows", "5", "--max-rows", "2"],
            "--min-rows 5 can never pass with --max-rows 2 (only that many rows are read)",
        ),
    ],
)
def test_cli_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        main([str(write_csv(THREE_ROWS)), *args])
    assert exc.value.code == 2
    assert message in capsys.readouterr().err
