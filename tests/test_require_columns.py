"""Tests for the --require-columns quality gate (issue #21)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.checks import CHECK_REQUIRED_COLUMN, evaluate
from csv_quality_report.cli import main
from csv_quality_report.errors import EXIT_CHECKS
from csv_quality_report.profile import profile_file

WriteCsv = Callable[..., Path]
DATA = "shipment_id,date,weight_kg\n1,2026-10-01,12.5\n2,2026-10-02,3\n"


def run(
    path: Path, capsys: pytest.CaptureFixture[str], *extra: str
) -> tuple[int, dict[str, Any], str]:
    code = main([str(path), "--format", "json", *extra])
    captured = capsys.readouterr()
    report: dict[str, Any] = json.loads(captured.out)
    return code, report, captured.err


def test_all_required_columns_present(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, rep, err = run(write_csv(DATA), capsys, "--require-columns", "shipment_id,date")
    assert (code, err) == (0, "")
    assert rep["checks"] == [
        {
            "check": "required_column",
            "column": "shipment_id",
            "limit": 1,
            "value": 1,
            "passed": True,
        },
        {"check": "required_column", "column": "date", "limit": 1, "value": 1, "passed": True},
    ]


def test_missing_column_fails_and_lists_available_columns(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, rep, err = run(write_csv(DATA), capsys, "--require-columns", "date, carrier ")
    assert code == EXIT_CHECKS
    assert [(c["column"], c["passed"]) for c in rep["checks"]] == [
        ("date", True),
        ("carrier", False),
    ]
    assert err == (
        "check failed: required column 'carrier' is missing "
        "(columns: shipment_id, date, weight_kg)\n"
    )


def test_matching_is_case_sensitive(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = run(write_csv(DATA), capsys, "--require-columns", "Date")
    assert code == EXIT_CHECKS
    assert "required column 'Date' is missing" in err


def test_matches_the_reported_header_after_duplicate_suffixes(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = run(write_csv("a,a\n1,2\n"), capsys, "--require-columns", "a,a_2")
    assert code == 0


def test_long_headers_are_truncated_in_the_message(write_csv: WriteCsv) -> None:
    header = ",".join(f"c{i}" for i in range(15))
    report = profile_file(write_csv(header + "\n" + ",".join("1" * 15) + "\n"))
    [result] = evaluate(report, required_columns=["missing"])
    assert result.check == CHECK_REQUIRED_COLUMN
    assert result.describe().endswith("(columns: c0, c1, c2, c3, c4, c5, c6, c7, c8, c9, ...)")


def test_repeated_names_give_one_check(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA))
    assert len(evaluate(report, required_columns=["date", "date"])) == 1


def test_works_together_with_other_gates(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code, rep, err = run(
        write_csv(DATA + "1,2026-10-01,12.5\n"),
        capsys,
        "--max-duplicates=0",
        "--require-columns",
        "carrier",
        "--max-missing",
        "0",
    )
    assert code == EXIT_CHECKS
    assert [c["check"] for c in rep["checks"] if not c["passed"]] == [
        "max_duplicates",
        "required_column",
    ]
    assert err.count("check failed:") == 2


def test_markdown_lists_required_columns(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write_csv(DATA)), "--require-columns", "date,carrier"]) == EXIT_CHECKS
    out = capsys.readouterr().out
    assert "- pass: required column 'date' is present\n" in out
    assert (
        "- FAIL: required column 'carrier' is missing (columns: shipment_id, date, weight_kg)\n"
        in out
    )


@pytest.mark.parametrize("bad", ["", ",", " , "])
def test_empty_name_list_is_a_usage_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(DATA)), "--require-columns", bad])
    assert excinfo.value.code == 2
    assert "invalid --require-columns value" in capsys.readouterr().err
