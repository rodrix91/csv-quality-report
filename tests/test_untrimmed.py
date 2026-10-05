"""Tests for the per-column count of untrimmed cells (issue #36)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.profile import _BATCH_ROWS, build_report, profile_file
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]


def columns(path: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *extra]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return {c["name"]: c for c in report["columns"]}


def test_counts_leading_and_trailing_whitespace(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    cols = columns(write_csv("code,city\nAR ,La Paz\n AR,La Paz\nAR,\tTarija\nBO,Tarija\n"), capsys)
    assert cols["code"]["untrimmed"] == 2
    assert cols["city"]["untrimmed"] == 1
    # Values are still compared after stripping.
    assert cols["code"]["top_values"][0] == {"value": "AR", "count": 3}
    assert cols["code"]["distinct"] == 2


def test_whitespace_only_cells_are_missing_not_untrimmed(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    col = columns(write_csv("a\n1\n   \n\t\n2\n"), capsys)["a"]
    assert (col["missing"], col["untrimmed"], col["type"]) == (2, 0, "int")


def test_padded_na_tokens_are_missing_not_untrimmed(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    col = columns(write_csv("a\n1\n NA \n2 \n"), capsys, "--na", "NA")["a"]
    assert (col["missing"], col["untrimmed"]) == (1, 1)


def test_inner_spaces_do_not_count(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert columns(write_csv("c\nLa Paz\nSanta Cruz\n"), capsys)["c"]["untrimmed"] == 0


def test_first_seen_tie_order_follows_the_first_raw_spelling(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # " b" is seen before "a"; after stripping, b and a tie and b must come first.
    col = columns(write_csv("v\n b\na\n"), capsys)["v"]
    assert [t["value"] for t in col["top_values"]] == ["b", "a"]


def test_numbers_with_padding_keep_their_type_and_range(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    col = columns(write_csv("n\n 10\n2 \n7\n"), capsys)["n"]
    assert (col["type"], col["min"], col["max"], col["untrimmed"]) == ("int", 2, 10, 2)


def test_counts_across_batches(write_csv: WriteCsv) -> None:
    rows = "".join(f"{i % 3} \n" for i in range(_BATCH_ROWS + 5))
    report = profile_file(write_csv("v\n" + rows))
    assert report.columns[0].untrimmed == _BATCH_ROWS + 5
    assert report.columns[0].distinct == 3


def test_duplicate_rows_still_compare_raw_text(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("a,b\n1,x\n1,x \n1,x\n"))
    assert report.duplicate_rows == 1


def test_streaming_and_in_memory_agree(write_csv: WriteCsv) -> None:
    path = write_csv("a,b\n x ,1\nx,2 \n , \n")
    assert profile_file(path) == build_report(read_table(path))


def test_markdown_line_only_when_present(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write_csv("a|x,b\n1 ,2\n 3,4\n5,6 \n"))]) == 0
    assert "- Untrimmed values: a\\|x (2), b (1)\n" in capsys.readouterr().out
    assert main([str(write_csv("a,b\n1,2\n"))]) == 0
    assert "Untrimmed" not in capsys.readouterr().out
