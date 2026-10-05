"""Tests for header names with surrounding whitespace (issue #39)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report.checks import evaluate
from csv_quality_report.cli import main
from csv_quality_report.errors import EXIT_CHECKS
from csv_quality_report.profile import build_report, profile_file
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]
DATA = "id, date ,city\n1,2026-01-01,La Paz\n"


def test_names_are_kept_as_read_and_listed(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA))
    assert [c.name for c in report.columns] == ["id", " date ", "city"]
    assert report.untrimmed_columns == (" date ",)


def test_clean_header_has_no_untrimmed_columns(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write_csv("a,b\n1,2\n")), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["untrimmed_columns"] == []
    assert main([str(write_csv("a,b\n1,2\n"))]) == 0
    assert "Column names with surrounding whitespace" not in capsys.readouterr().out


def test_json_and_markdown_output(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv("\tid| x ,y\n1,2,3\n".replace("|", ","))
    assert main([str(path), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["untrimmed_columns"] == ["\tid", " x "]
    assert main([str(path)]) == 0
    out = capsys.readouterr().out
    assert '- Column names with surrounding whitespace: "\tid", " x "\n' in out


def test_required_column_failure_suggests_the_padded_name(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write_csv(DATA)), "--require-columns", "date"]) == EXIT_CHECKS
    err = capsys.readouterr().err
    assert err.endswith("; did you mean ' date '?\n")


def test_column_limit_for_padded_name_also_gets_the_hint(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA))
    [result] = evaluate(report, column_max_missing={"date": 0})
    assert result.describe().endswith("; did you mean ' date '?")


def test_no_hint_when_nothing_matches(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA))
    [result] = evaluate(report, required_columns=["carrier"])
    assert "did you mean" not in result.describe()
    assert result.hint == ""


def test_padded_required_name_matches_a_clean_column(write_csv: WriteCsv) -> None:
    # The reverse case: the user typed spaces, the file is clean.
    report = profile_file(write_csv("city\nX\n"))
    [result] = evaluate(report, required_columns=[" city"])
    assert not result.passed and result.hint == "city"


def test_hint_is_not_part_of_the_json(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    main([str(write_csv(DATA)), "--format", "json", "--require-columns", "date"])
    [check] = json.loads(capsys.readouterr().out)["checks"]
    assert set(check) == {"check", "column", "limit", "value", "passed"}


def test_streaming_and_in_memory_agree(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    assert profile_file(path) == build_report(read_table(path))
