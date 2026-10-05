"""Tests for min_length / max_length per column (issue #49)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.profile import build_report, profile_file
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]


def columns(path: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *extra]) == 0
    return {c["name"]: c for c in json.loads(capsys.readouterr().out)["columns"]}


def test_lengths_reveal_a_truncated_code(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    col = columns(write_csv("country\nAR\nBO\nP\nPY\n"), capsys)["country"]
    assert (col["min_length"], col["max_length"]) == (1, 2)


def test_lengths_ignore_missing_cells_and_surrounding_spaces(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    col = columns(write_csv("c\n  AR \n\nBOL\nNA\n"), capsys, "--na", "NA")["c"]
    assert (col["min_length"], col["max_length"]) == (2, 3)


def test_lengths_count_characters_not_bytes(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    col = columns(write_csv("city\nAsunción\nSão Paulo\n"), capsys)["city"]
    assert (col["min_length"], col["max_length"]) == (8, 9)


def test_numeric_and_date_columns_have_lengths_too(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    cols = columns(write_csv("n,d\n7,2026-01-01\n12345,2026-12-31\n"), capsys)
    assert (cols["n"]["min_length"], cols["n"]["max_length"]) == (1, 5)
    assert (cols["d"]["min_length"], cols["d"]["max_length"]) == (10, 10)


def test_empty_column_has_no_lengths(write_csv: WriteCsv) -> None:
    col = profile_file(write_csv("a,b\n1,\n2,  \n")).columns[1]
    assert (col.min_length, col.max_length) == (None, None)


def test_streaming_and_in_memory_agree(write_csv: WriteCsv) -> None:
    path = write_csv("a,b\nxy,1\nz,22\n")
    assert profile_file(path) == build_report(read_table(path))
