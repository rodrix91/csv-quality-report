"""Tests for min/max of date columns (issue #11)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main

WriteCsv = Callable[..., Path]


def column(path: Path, capsys: pytest.CaptureFixture[str], name: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json"]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    found: dict[str, Any] = next(c for c in report["columns"] if c["name"] == name)
    return found


def test_date_range_is_reported_as_iso_strings(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("d\n2026-03-01\n2025-12-31\n\n2026-10-05\n2026-03-01\n")
    col = column(path, capsys, "d")
    assert col["type"] == "date"
    assert (col["min"], col["max"]) == ("2025-12-31", "2026-10-05")


def test_date_range_ignores_missing_and_surrounding_spaces(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("d,x\n  2024-02-29 ,1\n,2\n2024-01-01,3\n")
    col = column(path, capsys, "d")
    assert (col["min"], col["max"], col["missing"]) == ("2024-01-01", "2024-02-29", 1)


def test_single_date(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    col = column(write_csv("d\n2000-01-01\n"), capsys, "d")
    assert (col["min"], col["max"]) == ("2000-01-01", "2000-01-01")


def test_invalid_calendar_date_makes_string_without_range(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    col = column(write_csv("d\n2026-02-30\n2026-01-01\n"), capsys, "d")
    assert (col["type"], col["min"], col["max"]) == ("string", None, None)


def test_bool_and_string_columns_still_have_no_range(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("b,s\ntrue,x\nfalse,y\n")
    for name in ("b", "s"):
        col = column(path, capsys, name)
        assert (col["min"], col["max"]) == (None, None)


def test_markdown_shows_the_date_range(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("d\n2026-01-02\n2026-01-01\n")
    assert main([str(path)]) == 0
    assert "| d | date | 0 | 0.0 | 2 | 2026-01-01 | 2026-01-02 |" in capsys.readouterr().out
