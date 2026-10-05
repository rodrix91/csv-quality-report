"""Tests for ``--top N`` (issue #20)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.profile import TOP_N, build_report, profile_file
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]
DATA = "carrier\n" + "".join(f"C{i}\n" * (10 - i) for i in range(8))  # C0 x10 ... C7 x3


def tops(path: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *extra]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


def test_default_is_three(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    rep = tops(write_csv(DATA), capsys)
    assert TOP_N == 3
    assert rep["top_n"] == 3
    assert [t["value"] for t in rep["columns"][0]["top_values"]] == ["C0", "C1", "C2"]


@pytest.mark.parametrize("n", [1, 5, 8, 20])
def test_custom_top_n(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], n: int) -> None:
    rep = tops(write_csv(DATA), capsys, "--top", str(n))
    values = rep["columns"][0]["top_values"]
    assert rep["top_n"] == n
    assert len(values) == min(n, 8)  # never more than the distinct values
    assert values[0] == {"value": "C0", "count": 10}


def test_zero_lists_no_values(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    rep = tops(write_csv(DATA), capsys, "--top", "0")
    col = rep["columns"][0]
    assert (col["top_values"], col["distinct"]) == ([], 8)


def test_ties_keep_first_seen_order(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = tops(write_csv("v\nb\na\nc\nd\n"), capsys, "--top", "4")
    assert [t["value"] for t in rep["columns"][0]["top_values"]] == ["b", "a", "c", "d"]


def test_markdown_header_shows_n(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv(DATA)
    assert main([str(path), "--top", "5"]) == 0
    out = capsys.readouterr().out
    assert "| Top 5 values |" in out
    assert "C4 (6)" in out and "C5" not in out


def test_markdown_default_header_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write_csv(DATA))]) == 0
    assert "| Min | Max | Top 3 values |\n" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["-1", "x", "2.5"])
def test_invalid_top_is_usage_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(DATA)), f"--top={bad}"])
    assert excinfo.value.code == 2


def test_streaming_and_in_memory_agree(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    assert profile_file(path, top_n=6) == build_report(read_table(path), top_n=6)
