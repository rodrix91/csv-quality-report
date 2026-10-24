"""Tests for ``--skip-lines``: title lines before the header (issue #161)."""

from __future__ import annotations

import gzip
import io
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from csv_quality_report.cli import main
from csv_quality_report.errors import (
    DelimiterDetectionError,
    EmptyFileError,
    EncodingError,
    RaggedRowError,
)
from csv_quality_report.profile import build_report, profile_file
from csv_quality_report.reader import (
    MAX_TITLE_LINES,
    SNIFF_CHARS,
    _skip,
    open_rows,
    read_table,
    title_lines,
)

WriteCsv = Callable[..., Path]
ERP = (
    "Reporte de ventas por sucursal\r\n"
    "Generado: 22/10/2026 08:00\r\n"
    "\r\n"
    "Sucursal;Fecha;Importe\r\n"
    "Centro;21/10/2026;1.234,56\r\n"
    "Norte;21/10/2026;99,90\r\n"
)


def run_json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert main([*args, "--format", "json"]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


def test_title_lines_are_skipped(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = str(write_csv(ERP))
    report = run_json(
        capsys,
        path,
        "--delimiter",
        ";",
        "--skip-lines",
        "3",
        "--decimal-comma",
        "--thousands",
        "dot",
    )
    assert [c["name"] for c in report["columns"]] == ["Sucursal", "Fecha", "Importe"]
    assert (report["rows"], report["skipped_lines"]) == (2, 3)
    assert report["columns"][2]["type"] == "float"
    # The key sits right after sep_line.
    keys = list(report)
    assert keys[keys.index("sep_line") + 1] == "skipped_lines"


def test_without_the_title_lines_the_file_fails_with_a_hint(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(ERP))
    assert main([path, "--delimiter", ";"]) == 6
    assert capsys.readouterr().err == (
        "error: row at line 4 has 3 fields, expected 1 (from the header); if this row is "
        "the header and the lines before it are titles, skip them with --skip-lines 3\n"
    )
    assert main([path, "--delimiter", "auto"]) == 7
    assert capsys.readouterr().err == (
        "error: cannot detect the delimiter: no separator gives the same number of fields "
        "on every line; pass it explicitly with --delimiter; if the file starts with 2 title "
        "lines before the header, skip them with --skip-lines 2\n"
    )
    # The suggested counts work (the blank third line is skipped like any blank line).
    for count in ("2", "3"):
        assert main([path, "--delimiter", "auto", "--skip-lines", count]) == 0
        assert "| Importe |" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("data", "skip", "hinted"),
    [
        ("Titulo\na;b\n", 0, True),  # a one-field header and a wider row
        ("a;b\n1;2;3\n", 0, False),  # the header has several fields
        ("x\nTitulo\na;b\n", 1, False),  # lines were already skipped
    ],
)
def test_the_hint_only_appears_for_a_one_field_header(
    write_csv: WriteCsv, data: str, skip: int, hinted: bool
) -> None:
    with pytest.raises(RaggedRowError) as info:
        profile_file(write_csv(data), delimiter=";", skip_lines=skip)
    assert ("--skip-lines" in str(info.value)) is hinted


def test_the_suggested_count_ignores_a_sep_line(write_csv: WriteCsv) -> None:
    with pytest.raises(RaggedRowError, match="skip them with --skip-lines 2$"):
        profile_file(write_csv("sep=;\nT1\nT2\nid;n\n1;2\n"), delimiter="auto")


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("Titulo\na;b\n1;2\n", 1),
        ("T1\nT2: 01/10/2026\n\na;b\n1;2\n", 2),  # blank lines after the titles are free
        ("T1\r\nT2\r\na\tb\r\n1\tb\r\n", 2),
        ("Titulo\na;b\n", 1),  # a header-only export after its title
        ("a;b\n1;2;3\n", None),  # the dropped line has separators: not a title
        ("Titulo\na;b\n1;2;3\n", None),  # ragged after the title too
        ("T1\nT2\n", None),  # one column left: nothing to suggest
        ("T1\n\n\n", None),  # only blank lines left
        ("Titulo\n", None),  # nothing left after the title
        ("a;b\n" * 1 + "x\n" * 25 + "c;d\n1;2\n", None),  # more than 20 lines to drop
    ],
)
def test_title_lines(sample: str, expected: int | None) -> None:
    assert title_lines(sample) == expected


def test_title_lines_up_to_the_limit() -> None:
    titles = "".join(f"T{i}\n" for i in range(MAX_TITLE_LINES))
    assert title_lines(titles + "a;b\n1;2\n") == MAX_TITLE_LINES
    assert title_lines("T\n" + titles + "a;b\n1;2\n") is None


def test_no_suggestion_when_lines_are_already_skipped(write_csv: WriteCsv) -> None:
    path = write_csv("T1\nT2\na;b\n1;2\n")
    with pytest.raises(DelimiterDetectionError) as info:
        profile_file(path, delimiter="auto", skip_lines=1)
    assert "--skip-lines" not in str(info.value)
    with pytest.raises(
        DelimiterDetectionError,
        match="1 title line before the header, skip it with --skip-lines 1$",
    ):
        profile_file(write_csv("T1\na;b\n1;2\n", "one.csv"), delimiter="auto")


def test_zero_is_the_default_and_changes_nothing(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv("a;b\n1;2\n"))
    for fmt in ("markdown", "json"):
        assert main([path, "--delimiter", ";", "--format", fmt]) == 0
        plain = capsys.readouterr().out
        assert main([path, "--delimiter", ";", "--format", fmt, "--skip-lines", "0"]) == 0
        assert capsys.readouterr().out == plain
        assert "kipped" not in plain


def test_markdown_counts_the_skipped_lines(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write_csv(ERP)), "--delimiter", ";", "--skip-lines", "3"]) == 0
    out = capsys.readouterr().out
    assert "\n- Delimiter: semicolon\n- Skipped lines: 3 (before the header)\n" in out


def test_detection_samples_the_lines_after_the_skipped_ones(write_csv: WriteCsv) -> None:
    path = write_csv(ERP)
    report = profile_file(path, delimiter="auto", skip_lines=3)
    assert (report.delimiter, report.delimiter_detected, report.rows) == (";", True, 2)


def test_a_skipped_line_longer_than_the_sample(write_csv: WriteCsv) -> None:
    title = "x" * (SNIFF_CHARS + 10)
    report = profile_file(write_csv(f"{title}\na;b\n1;2\n"), delimiter="auto", skip_lines=1)
    assert (report.delimiter, [c.name for c in report.columns]) == (";", ["a", "b"])


def test_a_header_longer_than_the_sample_after_skipped_lines(write_csv: WriteCsv) -> None:
    columns = SNIFF_CHARS // 10 + 5
    header = ";".join(f"column_{i:03d}" for i in range(columns))
    row = ";".join("1" for _ in range(columns))
    report = profile_file(write_csv(f"Titulo\n{header}\n{row}\n"), delimiter="auto", skip_lines=1)
    assert (report.delimiter, len(report.columns), report.rows) == (";", columns, 1)


def test_skipped_lines_are_text_lines_not_records(write_csv: WriteCsv) -> None:
    # An unbalanced quote in a title line would swallow the header if the
    # title were parsed as CSV.
    path = write_csv('Reporte "ventas\na,b\n1,2\n')
    report = profile_file(path, skip_lines=1)
    assert ([c.name for c in report.columns], report.rows) == (["a", "b"], 1)


@pytest.mark.parametrize("end", ["\n", "\r\n", "\r"])
def test_line_endings(write_csv: WriteCsv, end: str) -> None:
    path = write_csv(end.join(["Titulo", "Fecha: hoy", "a,b", "1,2", "3,4"]) + end)
    report = profile_file(path, skip_lines=2)
    assert ([c.name for c in report.columns], report.rows) == (["a", "b"], 2)


def test_blank_title_lines_count(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("\n\n  \na,b\n1,2\n"), skip_lines=3)
    assert [c.name for c in report.columns] == ["a", "b"]


def test_error_line_numbers_count_the_skipped_lines(write_csv: WriteCsv) -> None:
    path = write_csv("T1\nT2\na;b\n1;2\n3\n")  # the short row is line 5 of the file
    with pytest.raises(RaggedRowError, match="row at line 5 has 1 fields, expected 2"):
        profile_file(path, delimiter=";", skip_lines=2)
    long = write_csv("T1\na,b\n1," + "x" * 200 + "\n", "long.csv")
    with pytest.raises(RaggedRowError, match="malformed CSV near line 3"):
        profile_file(long, skip_lines=1, max_field_size=100)


def test_after_an_excel_sep_line(write_csv: WriteCsv) -> None:
    # The sep= line is not counted in --skip-lines; line numbers count both.
    path = write_csv("sep=;\nReporte\nid;n\n1;2\n3\n")
    with pytest.raises(RaggedRowError, match="row at line 5 has 1 fields"):
        profile_file(path, delimiter="auto", skip_lines=1)
    good = write_csv("sep=;\nReporte\nid;n\n1;2\n", "good.csv")
    report = profile_file(good, delimiter="auto", skip_lines=1)
    assert (report.sep_line, report.skipped_lines, report.delimiter) == (True, 1, ";")
    assert [c.name for c in report.columns] == ["id", "n"]


def test_a_sep_line_after_the_title_is_data(write_csv: WriteCsv) -> None:
    # Only the first line of the file can declare the separator.
    report = profile_file(write_csv("Titulo\nsep=;\nx\n"), skip_lines=1)
    assert (report.sep_line, [c.name for c in report.columns]) == (False, ["sep=;"])


@pytest.mark.parametrize(
    ("data", "skip", "message"),
    [
        ("", 1, "it ends within the 1 lines skipped by --skip-lines"),
        ("T1\nT2\n", 3, "it ends within the 3 lines skipped by --skip-lines"),
        ("T1\nT2\n", 2, "it ends within the 2 lines skipped by --skip-lines"),
        ("T1\nT2", 2, "it ends within the 2 lines skipped by --skip-lines"),
        ("sep=;\nT1\n", 1, "it ends within the 1 lines skipped by --skip-lines"),
        ("T1\n\n\n", 1, "has no header row after the 1 lines skipped by --skip-lines"),
    ],
)
def test_no_header_left(write_csv: WriteCsv, data: str, skip: int, message: str) -> None:
    with pytest.raises(EmptyFileError, match=message):
        profile_file(write_csv(data), delimiter="auto", skip_lines=skip)


def test_no_header_left_is_exit_code_5(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("T1\n")
    assert main([str(path), "--skip-lines", "4"]) == 5
    assert capsys.readouterr().err == (
        f"error: '{path}' has no header row: it ends within the 4 lines skipped by --skip-lines\n"
    )


def test_an_empty_file_without_the_option_keeps_its_message(write_csv: WriteCsv) -> None:
    with pytest.raises(EmptyFileError, match=r"is empty \(no header row\)$"):
        profile_file(write_csv("\n\n"))


def test_encoding_and_invalid_bytes_in_skipped_lines(write_csv: WriteCsv) -> None:
    data = "Informe de stock: depósito\nCódigo;Año\nÑ1;2026\n".encode("cp1252")
    report = profile_file(write_csv(data), delimiter=";", encoding="cp1252", skip_lines=1)
    assert [c.name for c in report.columns] == ["Código", "Año"]
    # Read as UTF-8, the cp1252 title fails as an encoding error, with its offset.
    with pytest.raises(EncodingError, match="invalid byte at offset 21"):
        profile_file(write_csv(data, "utf8.csv"), delimiter=";", skip_lines=1)


def test_standard_input_and_gzip(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.BufferedReader(io.BytesIO(gzip.compress(ERP.encode())))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(buffer, encoding="utf-8"))
    report = profile_file(Path("-"), delimiter="auto", skip_lines=3)
    assert (report.compressed, report.skipped_lines, report.delimiter, report.rows) == (
        True,
        3,
        ";",
        2,
    )


def test_max_rows_counts_data_rows_only(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(ERP), delimiter=";", skip_lines=3, max_rows=1)
    assert (report.rows, report.truncated) == (1, True)


def test_in_memory_and_streaming_agree(write_csv: WriteCsv) -> None:
    path = write_csv(ERP)
    table = read_table(path, delimiter=";", skip_lines=3)
    assert (table.skipped_lines, table.header) == (3, ["Sucursal", "Fecha", "Importe"])
    assert build_report(table) == profile_file(path, delimiter=";", skip_lines=3)
    with open_rows(path, delimiter=";", skip_lines=3) as stream:
        assert stream.skipped_lines == 3 and len(list(stream)) == 2


def test_a_negative_count_is_refused(write_csv: WriteCsv) -> None:
    with pytest.raises(ValueError, match="skip_lines must be >= 0, got -1"):
        with open_rows(write_csv("a\n1\n"), skip_lines=-1):
            pass  # pragma: no cover - never reached


@pytest.mark.parametrize(("value", "error"), [("-1", "must be >= 0"), ("x", "invalid integer")])
def test_invalid_values_are_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], value: str, error: str
) -> None:
    with pytest.raises(SystemExit) as info:
        main([str(write_csv("a\n1\n")), "--skip-lines", value])
    assert info.value.code == 2
    assert f"argument --skip-lines: {error}" in capsys.readouterr().err


def test_a_huge_count_stops_reading_at_the_end_of_the_file() -> None:
    # --skip-lines 1000000000 on a short file must not call readline a billion times.
    class Handle:
        def __init__(self, text: str) -> None:
            self.lines = io.StringIO(text)
            self.calls = 0

        def readline(self) -> str:
            self.calls += 1
            return self.lines.readline()

    handle = Handle("T1\nT2\n")
    with pytest.raises(EmptyFileError, match="ends within the 1000000000 lines"):
        _skip(cast(io.TextIOWrapper, handle), "x.csv", "", 10**9)
    assert handle.calls == 3
