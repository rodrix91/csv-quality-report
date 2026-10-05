"""Tests for ``--na``: extra cell values counted as missing (issue #9)."""

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


def run_json(path: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *extra]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


def test_tokens_count_as_missing_and_restore_numeric_type(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("qty,city\n3,La Paz\nNA,null\n7,Tarija\n s/d ,\n")
    rep = run_json(path, capsys, "--na", "NA,null,s/d")
    qty, city = rep["columns"]
    assert (qty["type"], qty["missing"], qty["min"], qty["max"]) == ("int", 2, 3, 7)
    assert qty["missing_pct"] == 50.0
    assert (city["missing"], city["distinct"]) == (2, 2)
    assert rep["na_tokens"] == ["NA", "null", "s/d"]


def test_without_flag_tokens_are_ordinary_values(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = run_json(write_csv("qty\n3\nNA\n"), capsys)
    qty = rep["columns"][0]
    assert (qty["type"], qty["missing"]) == ("string", 0)
    assert rep["na_tokens"] == []


def test_tokens_are_case_sensitive_and_exact(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = run_json(write_csv("v\nNA\nna\nNAN\n"), capsys, "--na", "NA")
    v = rep["columns"][0]
    assert v["missing"] == 1
    assert [t["value"] for t in v["top_values"]] == ["na", "NAN"]


def test_tokens_are_removed_from_top_values_and_distinct(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = run_json(write_csv("v\n-\n-\n-\na\n"), capsys, "--na=-")
    v = rep["columns"][0]
    assert (v["missing"], v["distinct"], v["top_values"]) == (3, 1, [{"value": "a", "count": 1}])


def test_token_list_is_cleaned(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    rep = run_json(write_csv("v\n1\n"), capsys, "--na", " NA , ,null,NA,")
    assert rep["na_tokens"] == ["NA", "null"]


@pytest.mark.parametrize("bad", ["", ",", " , "])
def test_empty_token_list_is_a_usage_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv("v\n1\n")), "--na", bad])
    assert excinfo.value.code == 2
    assert "invalid --na value" in capsys.readouterr().err


def test_duplicate_rows_still_compare_raw_text(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # "NA" and "" are both missing, but the rows are not the same text.
    rep = run_json(write_csv("a,b\n1,NA\n1,\n1,NA\n"), capsys, "--na", "NA")
    assert rep["duplicate_rows"] == 1


def test_markdown_lists_tokens_only_when_given(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("v\n1\nNA\n")
    assert main([str(path), "--na", "NA,a|b"]) == 0
    assert "- Also counted as missing: `NA`, `a\\|b`\n" in capsys.readouterr().out
    assert main([str(path)]) == 0
    assert "Also counted as missing" not in capsys.readouterr().out


def test_streaming_and_in_memory_agree(write_csv: WriteCsv) -> None:
    path = write_csv("a,b\nNA,1\n2,null\n,3\n")
    tokens = ("NA", "null")
    assert profile_file(path, na_tokens=tokens) == build_report(read_table(path), na_tokens=tokens)
