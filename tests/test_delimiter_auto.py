"""Tests for ``--delimiter auto`` and ``detect_delimiter``."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.errors import EXIT_DELIMITER, DelimiterDetectionError
from csv_quality_report.reader import SNIFF_CHARS, detect_delimiter

WriteCsv = Callable[..., Path]


def run_json(path: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *extra]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


@pytest.mark.parametrize("sep", [",", ";", "\t", "|"])
def test_detects_each_candidate(sep: str) -> None:
    text = sep.join(["id", "name", "city"]) + "\n" + sep.join(["1", "Ana", "Tarija"]) + "\n"
    assert detect_delimiter(text) == sep


def test_semicolon_with_decimal_commas_is_not_mistaken_for_comma() -> None:
    # Comma gives 2 fields on the header but 3 on data rows: inconsistent.
    text = "sku;price\nA1;10,5\nB2;7,25\n"
    assert detect_delimiter(text) == ";"


def test_quoted_fields_containing_other_candidates() -> None:
    text = 'name,notes\nAna,"a;b|c"\nLuis,"x;y"\n'
    assert detect_delimiter(text) == ","


def test_quoted_newlines_do_not_break_detection() -> None:
    text = 'id;comment\n1;"first line\nsecond line"\n2;ok\n'
    assert detect_delimiter(text) == ";"


def test_single_column_file_defaults_to_comma() -> None:
    assert detect_delimiter("value\n1\n2\n") == ","


def test_empty_text_defaults_to_comma() -> None:
    assert detect_delimiter("") == ","


def test_ambiguous_file_is_an_error_listing_candidates() -> None:
    with pytest.raises(DelimiterDetectionError) as excinfo:
        detect_delimiter("a,b;c\n1,2;3\n")
    assert "several separators fit every line (comma, semicolon)" in excinfo.value.message


def test_inconsistent_file_is_an_error() -> None:
    with pytest.raises(DelimiterDetectionError) as excinfo:
        detect_delimiter("a,b\n1,2,3\n4\n")
    assert "no separator gives the same number of fields" in excinfo.value.message


def test_only_the_first_lines_are_checked() -> None:
    # A ragged row far below the sample window must not prevent detection;
    # it is reported later by the reader as a ragged row.
    rows = "".join(f"{i};x\n" for i in range(200))
    assert detect_delimiter("n;v\n" + rows + "1;2;3\n") == ";"


def test_cut_off_last_line_of_the_sample_is_ignored() -> None:
    line = "aaaa;bbbb\n"
    body = line * (SNIFF_CHARS // len(line))
    # The sample window ends in the middle of a line that would look ragged.
    text = body + "cccc" + ";" * 50 + "\n"
    assert len(text) > SNIFF_CHARS
    assert detect_delimiter(text) == ";"


def test_cli_auto_reports_detected_delimiter_json(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("sku;price\nA1;10,5\nB2;7,25\n")
    rep = run_json(path, capsys, "--delimiter", "auto", "--decimal-comma")
    assert (rep["delimiter"], rep["delimiter_detected"]) == (";", True)
    assert rep["columns"][1]["type"] == "float"


def test_cli_auto_reports_detected_delimiter_markdown(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a\tb\n1\t2\n")
    assert main([str(path), "--delimiter", "AUTO"]) == 0
    assert "- Delimiter: tab (detected)\n" in capsys.readouterr().out


def test_cli_explicit_non_comma_delimiter_is_shown(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a|b\n1|2\n")
    assert main([str(path), "--delimiter", "|"]) == 0
    out = capsys.readouterr().out
    assert "- Delimiter: pipe\n" in out
    assert "(detected)" not in out


def test_cli_unusual_explicit_delimiter_is_shown_as_code(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a:b\n1:2\n")
    assert main([str(path), "--delimiter", ":"]) == 0
    assert "- Delimiter: `:`\n" in capsys.readouterr().out


def test_cli_default_comma_adds_no_delimiter_line(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a,b\n1,2\n")
    assert main([str(path)]) == 0
    assert "Delimiter" not in capsys.readouterr().out


def test_cli_default_json_reports_comma(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = run_json(write_csv("a,b\n1,2\n"), capsys)
    assert (rep["delimiter"], rep["delimiter_detected"]) == (",", False)


def test_cli_detection_failure_exit_code(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a,b;c\n1,2;3\n")
    assert main([str(path), "--delimiter", "auto"]) == EXIT_DELIMITER
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: cannot detect the delimiter")
