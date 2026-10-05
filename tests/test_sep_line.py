"""Tests for Excel's ``sep=`` first line (issue #66)."""

from __future__ import annotations

import gzip
import io
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.errors import (
    DelimiterDetectionError,
    EmptyFileError,
    EncodingError,
    RaggedRowError,
)
from csv_quality_report.profile import build_report, profile_file
from csv_quality_report.reader import SNIFF_CHARS, declared_delimiter, open_rows, read_table

WriteCsv = Callable[..., Path]
EXCEL = "sep=;\r\nid;nombre;monto\r\n1;Ana;10,5\r\n2;Luis;7\r\n"


def report_json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert main([*args, "--format", "json"]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("sep=;", ";"),
        ("sep=;\r\n", ";"),
        ("sep=,\n", ","),
        ("SEP=|\r", "|"),
        ('"sep=\t"\n', "\t"),
        ('"sep=;"\r\n', ";"),
        ("sep=:\n", ":"),
        # Not a declaration: left as data.
        ("sep=\n", None),
        ("sep=;;\n", None),
        ("sep=; \n", None),
        (" sep=;\n", None),
        ('sep="\n', None),
        ("separator=;\n", None),
        ("id;sep=;\n", None),
        ("sep=;\n\n", None),
        ("", None),
    ],
)
def test_declared_delimiter(line: str, expected: str | None) -> None:
    assert declared_delimiter(line) == expected


def test_auto_follows_the_declaration(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(EXCEL), delimiter="auto", decimal_comma=True)
    assert (report.delimiter, report.delimiter_detected, report.sep_line) == (";", False, True)
    assert [c.name for c in report.columns] == ["id", "nombre", "monto"]
    assert (report.rows, report.columns[2].type) == (2, "float")


def test_matching_explicit_delimiter_skips_the_line(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(EXCEL), delimiter=";")
    assert (report.sep_line, report.rows, len(report.columns)) == (True, 2, 3)


def test_other_delimiter_is_refused(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(EXCEL)
    with pytest.raises(DelimiterDetectionError) as excinfo:
        profile_file(path)  # the default comma
    assert excinfo.value.message == (
        f"'{path}' declares the semicolon delimiter in its first line (sep=;), but the "
        "delimiter in use is comma; pass --delimiter auto to follow the file"
    )
    assert main([str(path), "--delimiter", ":"]) == 7
    assert "but the delimiter in use is ':'; pass --delimiter auto" in capsys.readouterr().err


def test_unnamed_declared_character_is_quoted(write_csv: WriteCsv) -> None:
    with pytest.raises(DelimiterDetectionError, match=r"declares the ':' delimiter"):
        profile_file(write_csv("sep=:\na:b\n"))
    assert profile_file(write_csv("sep=:\na:b\n1:2\n", "colon.csv"), delimiter="auto").rows == 1


def test_auto_detection_no_longer_fails_on_the_hint(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # The hint line has one field and the rest three, which made detection
    # refuse the file before.
    rep = report_json(capsys, str(write_csv(EXCEL)), "--delimiter", "auto")
    assert (rep["delimiter"], rep["sep_line"], rep["rows"]) == (";", True, 2)


def test_bom_quotes_and_case(write_csv: WriteCsv) -> None:
    path = write_csv(b'\xef\xbb\xbf"SEP=,"\r\na,b\r\n1,2\r\n')
    report = profile_file(path)
    assert (report.sep_line, [c.name for c in report.columns], report.rows) == (
        True,
        ["a", "b"],
        1,
    )


def test_standard_input_and_gzip(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.BufferedReader(io.BytesIO(gzip.compress(EXCEL.encode())))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(buffer, encoding="utf-8"))
    report = profile_file(Path("-"), delimiter="auto")
    assert (report.compressed, report.sep_line, report.delimiter, report.rows) == (
        True,
        True,
        ";",
        2,
    )


def test_cp1252_file_with_the_hint(write_csv: WriteCsv) -> None:
    path = write_csv("sep=;\r\nCiudad;Año\r\nAsunción;2026\r\n".encode("cp1252"))
    report = profile_file(path, delimiter="auto", encoding="cp1252")
    assert [c.name for c in report.columns] == ["Ciudad", "Año"]
    assert report.columns[0].top_values == [("Asunción", 1)]


def test_error_line_numbers_count_the_skipped_line(write_csv: WriteCsv) -> None:
    path = write_csv("sep=;\nid;n\n1;2\n3\n")  # the short row is line 4 of the file
    with pytest.raises(RaggedRowError, match="row at line 4 has 1 fields"):
        profile_file(path, delimiter="auto")
    long = write_csv("sep=,\na,b\n1," + "x" * 200 + "\n", "long.csv")
    with pytest.raises(RaggedRowError, match="malformed CSV near line 3"):
        profile_file(long, max_field_size=100)


def test_only_the_hint_is_an_empty_file(write_csv: WriteCsv) -> None:
    with pytest.raises(EmptyFileError, match="is empty"):
        profile_file(write_csv("sep=;\r\n"), delimiter="auto")


def test_only_the_first_line_is_checked(write_csv: WriteCsv) -> None:
    path = write_csv("note\nsep=;\nx\n")
    report = profile_file(path)
    assert (report.sep_line, report.columns[0].top_values) == (False, [("sep=;", 1), ("x", 1)])


def test_header_that_starts_like_the_hint_is_data(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("sep=x,y\n1,2\n"))
    assert (report.sep_line, [c.name for c in report.columns]) == (False, ["sep=x", "y"])


def test_files_without_the_hint_are_unchanged(write_csv: WriteCsv) -> None:
    path = write_csv("a;b\n1;2\n")
    report = profile_file(path, delimiter="auto")
    assert (report.delimiter_detected, report.sep_line) == (True, False)


def test_auto_detection_with_a_first_line_longer_than_the_sample(write_csv: WriteCsv) -> None:
    columns = SNIFF_CHARS // 10 + 5
    header = ";".join(f"column_{i:03d}" for i in range(columns))
    assert len(header) > SNIFF_CHARS
    row = ";".join(str(i) for i in range(columns))
    report = profile_file(write_csv(f"{header}\n{row}\n{row}\n"), delimiter="auto")
    assert (report.delimiter, len(report.columns), report.rows) == (";", columns, 2)


def test_markdown_says_where_the_delimiter_came_from(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write_csv(EXCEL)), "--delimiter", "auto"]) == 0
    assert "\n- Delimiter: semicolon (declared by a sep= line)\n" in capsys.readouterr().out
    # A declared comma is named too, although a comma is not normally mentioned.
    assert main([str(write_csv("sep=,\na,b\n1,2\n", "comma.csv"))]) == 0
    assert "\n- Delimiter: comma (declared by a sep= line)\n" in capsys.readouterr().out


def test_in_memory_and_streaming_agree(write_csv: WriteCsv) -> None:
    path = write_csv(EXCEL)
    table = read_table(path, delimiter="auto")
    assert table.sep_line
    assert build_report(table) == profile_file(path, delimiter="auto")
    with open_rows(path, delimiter=";") as stream:
        assert stream.sep_line and stream.header == ["id", "nombre", "monto"]


def test_a_long_first_line_does_not_read_the_whole_file(write_csv: WriteCsv) -> None:
    # Detection must stop after the first line when it already exceeds the
    # sample: an invalid byte far into the file is then found while the rows
    # are read, not while the file is opened (which would mean it was all
    # loaded into memory to build the sample).
    columns = SNIFF_CHARS // 10 + 5
    header = ";".join(f"column_{i:03d}" for i in range(columns))
    row = ";".join("1" for _ in range(columns))
    data = f"{header}\n" + f"{row}\n" * 20 + row[:-1]
    path = write_csv(data.encode() + b"\xff\n")
    with open_rows(path, delimiter="auto") as stream:
        assert (stream.delimiter, len(stream.header)) == (";", columns)
        with pytest.raises(EncodingError):
            for _ in stream:
                pass
