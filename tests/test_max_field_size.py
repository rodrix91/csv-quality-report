"""Tests for ``--max-field-size`` (issue #48)."""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from csv_quality_report.cli import main
from csv_quality_report.errors import RaggedRowError
from csv_quality_report.profile import build_report, profile_file
from csv_quality_report.reader import _guarded, open_rows, read_table

WriteCsv = Callable[..., Path]
DEFAULT_LIMIT = 131_072
LONG = "x" * 200_000


@pytest.fixture(autouse=True)
def _limit_is_the_default() -> None:
    assert csv.field_size_limit() == DEFAULT_LIMIT


def test_default_limit_rejects_long_fields_and_points_to_the_option(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write_csv(f"id,blob\n1,{LONG}\n"))]) == 6
    err = capsys.readouterr().err
    assert "field larger than field limit (131072)" in err
    assert err.rstrip().endswith("raise the limit with --max-field-size")


def test_raised_limit_reads_long_fields(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(f"id,blob\n1,{LONG}\n2,short\n")
    assert main([str(path), "--max-field-size", "300000"]) == 0
    assert "| blob | string | 0 | 0.0 | 2 |" in capsys.readouterr().out
    assert csv.field_size_limit() == DEFAULT_LIMIT  # restored after the run


def test_limit_is_restored_after_an_error(write_csv: WriteCsv) -> None:
    path = write_csv(f"id,blob\n1,{LONG}\n3\n")  # ragged row after the long field
    with pytest.raises(RaggedRowError):
        profile_file(path, max_field_size=300_000)
    assert csv.field_size_limit() == DEFAULT_LIMIT


def test_limit_applies_while_the_stream_is_open(write_csv: WriteCsv) -> None:
    with open_rows(write_csv("a\n1\n"), max_field_size=500_000) as stream:
        assert csv.field_size_limit() == 500_000
        list(stream)
    assert csv.field_size_limit() == DEFAULT_LIMIT


def test_a_field_over_the_raised_limit_still_fails(write_csv: WriteCsv) -> None:
    with pytest.raises(RaggedRowError) as excinfo:
        profile_file(write_csv(f"b\n{LONG}\n"), max_field_size=100_000)
    assert "field larger than field limit (100000)" in excinfo.value.message


def test_other_csv_errors_get_no_hint() -> None:
    # In its default (non-strict) mode the csv module raises csv.Error in
    # practice only for the field limit, so feed _guarded a different one.
    class Reader:
        line_num = 7

    def broken() -> Iterator[list[str]]:
        yield ["a"]
        raise csv.Error("some other problem")

    with pytest.raises(RaggedRowError) as excinfo:
        list(_guarded(Path("x.csv"), broken(), Reader()))
    assert excinfo.value.message == "malformed CSV near line 7: some other problem"


def test_long_fields_with_auto_detection(write_csv: WriteCsv) -> None:
    path = write_csv(f"id;blob\n1;{'y' * 150_000}\n2;z\n")
    report = profile_file(path, delimiter="auto", max_field_size=200_000)
    assert (report.delimiter, report.rows) == (";", 2)


@pytest.mark.parametrize("bad", ["0", "-5", "big"])
def test_invalid_values_are_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv("a\n1\n")), f"--max-field-size={bad}"])
    assert excinfo.value.code == 2


def test_streaming_and_in_memory_agree(write_csv: WriteCsv) -> None:
    path = write_csv(f"id,blob\n1,{LONG}\n")
    streamed = profile_file(path, max_field_size=300_000)
    assert streamed == build_report(read_table(path, max_field_size=300_000))
