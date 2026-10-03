"""Behavior tests: run the CLI through ``main`` and check stdout/stderr/exit code."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main

WriteCsv = Callable[..., Path]
ROOT = Path(__file__).resolve().parent.parent


def report_of(path: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *extra]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


def col(report: dict[str, Any], name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(c for c in report["columns"] if c["name"] == name)
    return found


# --- happy path -----------------------------------------------------------


def test_happy_path_types_and_stats(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(
        "n,x,flag,day,word\n1,1.5,true,2024-01-01,a\n2,2.5,false,2024-01-02,b\n3,0.5,true,2024-01-03,a\n"
    )
    rep = report_of(path, capsys)
    assert rep["rows"] == 3
    assert rep["duplicate_rows"] == 0
    assert [c["type"] for c in rep["columns"]] == ["int", "float", "bool", "date", "string"]
    assert (col(rep, "n")["min"], col(rep, "n")["max"]) == (1, 3)
    assert (col(rep, "x")["min"], col(rep, "x")["max"]) == (0.5, 2.5)
    assert col(rep, "word")["min"] is None
    assert col(rep, "word")["distinct"] == 2
    assert col(rep, "word")["top_values"][0] == {"value": "a", "count": 2}


def test_top_values_limited_to_three_with_stable_ties(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("v\nd\nc\nb\na\nd\n")
    top = col(report_of(path, capsys), "v")["top_values"]
    assert top == [
        {"value": "d", "count": 2},
        {"value": "c", "count": 1},
        {"value": "b", "count": 1},
    ]


def test_duplicate_rows_counted(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv("a,b\n1,x\n1,x\n1,x\n2,y\n")
    assert report_of(path, capsys)["duplicate_rows"] == 2


def test_markdown_is_default_format(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a\n1\n2\n")
    assert main([str(path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# CSV quality report:")
    assert "| a | int | 0 | 0.0 | 2 | 1 | 2 | 1 (1), 2 (1) |" in out


def test_sample_markdown_matches_readme() -> None:
    """The README embeds this exact output; keep them in sync."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "csv_quality_report", "examples/sample.csv"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout in readme


# --- missing values -------------------------------------------------------


def test_missing_values_counted_and_excluded(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a,b\n1,x\n,\n3, \n4,y\n")
    rep = report_of(path, capsys)
    a, b = col(rep, "a"), col(rep, "b")
    assert (a["missing"], a["missing_pct"], a["type"], a["min"], a["max"]) == (1, 25.0, "int", 1, 4)
    assert (b["missing"], b["missing_pct"], b["distinct"]) == (2, 50.0, 2)


def test_all_missing_column_is_string_without_min_max(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a,b\n1,\n2,\n")
    b = col(report_of(path, capsys), "b")
    assert (
        b["type"],
        b["missing"],
        b["missing_pct"],
        b["distinct"],
        b["min"],
        b["max"],
        b["top_values"],
    ) == (
        "string",
        2,
        100.0,
        0,
        None,
        None,
        [],
    )


def test_header_only_file_reports_zero_rows(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = report_of(write_csv("a,b\n"), capsys)
    assert rep["rows"] == 0
    assert col(rep, "a")["missing_pct"] == 0.0


def test_blank_lines_are_skipped(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert report_of(write_csv("a\n1\n\n2\n\n"), capsys)["rows"] == 2


def test_quoted_fields_with_commas_and_newlines(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv('a,b\n"x,y","line1\nline2"\n')
    rep = report_of(path, capsys)
    assert rep["rows"] == 1
    assert col(rep, "a")["top_values"] == [{"value": "x,y", "count": 1}]


# --- --max-rows -----------------------------------------------------------


def test_max_rows_limits_and_flags_truncation(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a\n1\n2\n3\n4\n")
    rep = report_of(path, capsys, "--max-rows", "2")
    assert (rep["rows"], rep["truncated"]) == (2, True)
    assert col(rep, "a")["max"] == 2


def test_max_rows_larger_than_file_not_truncated(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = report_of(write_csv("a\n1\n2\n"), capsys, "--max-rows", "2")
    assert (rep["rows"], rep["truncated"]) == (2, False)


@pytest.mark.parametrize("bad", ["0", "-1", "abc"])
def test_max_rows_invalid_is_usage_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        main([str(write_csv("a\n1\n")), "--max-rows", bad])
    assert exc.value.code == 2
    assert "--max-rows" in capsys.readouterr().err


# --- error handling and exit codes ---------------------------------------


def test_ragged_row_too_few_fields(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(write_csv("a,b,c\n1,2,3\n4,5\n"))])
    cap = capsys.readouterr()
    assert code == 6
    assert cap.out == ""
    assert "line 3" in cap.err and "2 fields" in cap.err and "expected 3" in cap.err


def test_ragged_row_too_many_fields(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([str(write_csv("a,b\n1,2,3\n"))])
    assert code == 6
    assert "3 fields" in capsys.readouterr().err


def test_empty_file(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(write_csv(b""))])
    cap = capsys.readouterr()
    assert code == 5
    assert cap.out == ""
    assert "empty" in cap.err


@pytest.mark.parametrize("content", ["\n\n", "\ufeff", "\r\n"])
def test_file_with_only_blank_content_is_empty(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], content: str
) -> None:
    assert main([str(write_csv(content))]) == 5
    assert "empty" in capsys.readouterr().err


def test_bad_encoding_latin1(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv("name\ncafé\n".encode("latin-1"))
    code = main([str(path)])
    cap = capsys.readouterr()
    assert code == 4
    assert cap.out == ""
    assert "not valid UTF-8" in cap.err and "offset" in cap.err


def test_utf16_file_is_reported_as_bad_encoding(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a\n1\n".encode("utf-16"))
    assert main([str(path)]) == 4
    assert "UTF-8" in capsys.readouterr().err


def test_utf8_bom_is_accepted_and_stripped_from_header(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(b"\xef\xbb\xbfid,name\n1,Z\xc3\xa9\n")
    rep = report_of(path, capsys)
    assert [c["name"] for c in rep["columns"]] == ["id", "name"]
    assert col(rep, "name")["top_values"] == [{"value": "Zé", "count": 1}]


def test_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(tmp_path / "nope.csv")])
    cap = capsys.readouterr()
    assert code == 3
    assert "cannot read" in cap.err


def test_directory_instead_of_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path)]) == 3
    assert "cannot read" in capsys.readouterr().err


def test_no_arguments_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_unknown_format_is_usage_error(write_csv: WriteCsv) -> None:
    with pytest.raises(SystemExit) as exc:
        main([str(write_csv("a\n1\n")), "--format", "xml"])
    assert exc.value.code == 2


def test_module_invocation_exit_code(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "csv_quality_report", str(tmp_path / "missing.csv")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 3
    assert proc.stdout == ""
    assert proc.stderr.startswith("error:")


# --- duplicate column names ----------------------------------------------


def test_duplicate_column_names_get_numeric_suffixes(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a,a,b,a\n1,2,x,3\n")
    rep = report_of(path, capsys)
    assert [c["name"] for c in rep["columns"]] == ["a", "a_2", "b", "a_3"]
    assert [col(rep, n)["max"] for n in ("a", "a_2", "a_3")] == [1, 2, 3]


def test_duplicate_column_suffix_avoids_existing_name(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = report_of(write_csv("a,a,a_2\n1,2,3\n"), capsys)
    names = [c["name"] for c in rep["columns"]]
    assert names == ["a", "a_3", "a_2"]
    assert len(set(names)) == 3
