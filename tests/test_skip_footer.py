"""Tests for ``--skip-footer``: totals rows and footer lines after the data (issue #192)."""

from __future__ import annotations

import gzip
import io
import json
import sys
import tracemalloc
from collections.abc import Callable, Iterator
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
from csv_quality_report.reader import (
    MAX_FOOTER_LINES,
    SNIFF_CHARS,
    _before_footer,
    _without_last_lines,
    detect_delimiter,
    footer_lines,
    open_rows,
    read_table,
)

WriteCsv = Callable[..., Path]
# An ERP export with a footer: an empty-cells row, a totals row and a record count.
ERP = (
    "Fecha;Cliente;Importe\r\n"
    "05/10/2026;Ferretería Sur;1.234,50\r\n"
    "06/10/2026;Agro Norte;980,00\r\n"
    ";;\r\n"
    "Total general;;2.214,50\r\n"
    "Cantidad de registros: 2\r\n"
)
READ = ("--decimal-comma", "--thousands", "dot", "--date-order", "dmy")


def run_json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert main([*args, "--format", "json"]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


def test_the_footer_is_dropped(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = str(write_csv(ERP))
    report = run_json(capsys, path, "--delimiter", ";", "--skip-footer", "3", *READ)
    assert report["rows"] == 2
    assert report["skipped_footer"] == 3
    # The key sits right after skipped_lines' place: after sep_line, before na_tokens.
    keys = list(report)
    assert keys.index("skipped_footer") == keys.index("sep_line") + 1
    assert keys.index("na_tokens") == keys.index("skipped_footer") + 1
    fecha, cliente, importe = report["columns"]
    assert (fecha["type"], fecha["min"], fecha["max"]) == ("date", "2026-10-05", "2026-10-06")
    assert (cliente["missing"], importe["max"], importe["mean"]) == (0, 1234.5, 1107.25)


def test_a_totals_row_left_in_is_profiled_as_data(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # Why the option exists: with only the record count dropped, the totals row
    # turns the date column into text and becomes the maximum of the amounts.
    path = str(write_csv(ERP))
    report = run_json(capsys, path, "--delimiter", ";", "--skip-footer", "1", *READ)
    fecha, _, importe = report["columns"]
    assert (report["rows"], fecha["type"], importe["max"]) == (4, "string", 2214.5)


def test_without_the_option_a_one_field_footer_fails_with_a_hint(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(ERP))
    assert main([path, "--delimiter", ";"]) == 6
    assert capsys.readouterr().err == (
        "error: row at line 6 has 1 fields, expected 3 (from the header); "
        "if this last record is a footer, skip it with --skip-footer 1 "
        "(add one for each totals row above it)\n"
    )


def test_the_hint_counts_every_ragged_record_to_the_end(write_csv: WriteCsv) -> None:
    data = "a;b;c\n1;2;3\nTotal;6\n\nRegistros: 1\nFin\n"
    with pytest.raises(RaggedRowError) as info:
        profile_file(write_csv(data), delimiter=";")
    assert info.value.message == (
        "row at line 3 has 2 fields, expected 3 (from the header); "
        "if this record and the 2 after it are a footer, skip them with --skip-footer 3 "
        "(add one for each totals row above them)"
    )
    # The suggested count works: blank lines are not counted.
    assert profile_file(write_csv(data), delimiter=";", skip_footer=3).rows == 1


def test_the_hint_says_both_for_two_records(write_csv: WriteCsv) -> None:
    with pytest.raises(RaggedRowError, match=r"skip both with --skip-footer 2 \("):
        profile_file(write_csv("a;b\n1;2\nTotal\nFin\n"), delimiter=";")


@pytest.mark.parametrize(
    "data",
    [
        pytest.param("a;b\n1\n3;4\n", id="a-later-record-has-the-header-width"),
        pytest.param("a;b\n1\n" + "x\n" * MAX_FOOTER_LINES, id="longer-than-the-limit"),
        pytest.param('a;b\n1\n"xyz\n', id="a-later-record-is-malformed"),
    ],
)
def test_no_footer_hint(write_csv: WriteCsv, data: str) -> None:
    with pytest.raises(RaggedRowError) as info:
        with open_rows(write_csv(data), delimiter=";", max_field_size=2) as stream:
            list(stream)
    assert info.value.message == "row at line 2 has 1 fields, expected 2 (from the header)"


def test_the_hint_reaches_the_limit(write_csv: WriteCsv) -> None:
    # A ragged record and MAX_FOOTER_LINES - 1 more: still a footer of the maximum size.
    data = "a;b\n1\n" + "x\n" * (MAX_FOOTER_LINES - 2)
    with pytest.raises(RaggedRowError, match=f"--skip-footer {MAX_FOOTER_LINES - 1} "):
        profile_file(write_csv(data), delimiter=";")
    data += "x\n"
    with pytest.raises(RaggedRowError, match=f"--skip-footer {MAX_FOOTER_LINES} "):
        profile_file(write_csv(data), delimiter=";")


def test_a_title_hint_wins_over_a_footer_hint(write_csv: WriteCsv) -> None:
    # A one-field header followed by wider rows is a title read as the header.
    with pytest.raises(RaggedRowError) as info:
        profile_file(write_csv("Reporte\na;b\n1;2\n"), delimiter=";")
    assert info.value.message.endswith("skip them with --skip-lines 1")


def test_no_hint_once_a_footer_is_skipped(write_csv: WriteCsv) -> None:
    with pytest.raises(RaggedRowError) as info:
        profile_file(write_csv("a;b\n1\nTotal\n"), delimiter=";", skip_footer=1)
    assert info.value.message == "row at line 2 has 1 fields, expected 2 (from the header)"


def test_footer_records_are_not_checked(write_csv: WriteCsv) -> None:
    data = "a;b\n1;2\nTotal;3;extra\nFin\n"
    assert profile_file(write_csv(data), delimiter=";", skip_footer=2).rows == 1


def test_a_ragged_data_row_still_fails_with_its_line(write_csv: WriteCsv) -> None:
    # The buffer delays rows; the error must still name the row's own line.
    data = "a;b\n1;2\n\n3\n4;5\n6;7\nFin\n"
    with pytest.raises(RaggedRowError) as info:
        profile_file(write_csv(data), delimiter=";", skip_footer=1)
    assert info.value.message == "row at line 4 has 1 fields, expected 2 (from the header)"


def test_line_numbers_of_multi_line_records(write_csv: WriteCsv) -> None:
    data = 'a;b\n"x\ny";2\n3\n4;5\nFin\n'
    with pytest.raises(RaggedRowError, match="row at line 4 has 1 fields"):
        profile_file(write_csv(data), delimiter=";", skip_footer=1)


def test_a_quoted_line_break_in_the_footer_is_one_record(write_csv: WriteCsv) -> None:
    data = 'a;b\n1;2\n"Generado por\nel sistema"\n'
    assert profile_file(write_csv(data), delimiter=";", skip_footer=1).rows == 1


def test_blank_lines_are_not_records(write_csv: WriteCsv) -> None:
    data = "a;b\n1;2\n3;4\n\n\nTotal;7\n\n"
    report = profile_file(write_csv(data), delimiter=";", skip_footer=1)
    assert (report.rows, report.columns[0].max) == (2, 3)


def test_zero_is_the_default_and_changes_nothing(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv("a;b\n1;2\n3;4\n"))
    for fmt in ("json", "markdown"):
        assert main([path, "--delimiter", ";", "--format", fmt]) == 0
        default = capsys.readouterr().out
        assert main([path, "--delimiter", ";", "--format", fmt, "--skip-footer", "0"]) == 0
        assert capsys.readouterr().out == default
        assert "kipped" not in default


@pytest.mark.parametrize(("count", "line"), [(1, "1 record"), (3, "3 records")])
def test_markdown_counts_the_skipped_records(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], count: int, line: str
) -> None:
    assert main([str(write_csv(ERP)), "--delimiter", ";", "--skip-footer", str(count)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert f"- Skipped footer: {line} (after the data)" in lines
    assert lines.index("- Delimiter: semicolon") + 1 == lines.index(
        f"- Skipped footer: {line} (after the data)"
    )


def test_with_title_lines(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = str(write_csv("Reporte de ventas\r\n\r\n" + ERP))
    report = run_json(
        capsys, path, "--delimiter", "auto", "--skip-lines", "2", "--skip-footer", "3"
    )
    assert (report["rows"], report["skipped_lines"], report["skipped_footer"]) == (2, 2, 3)
    assert report["delimiter"] == ";"
    assert main([path, "--delimiter", ";", "--skip-lines", "2", "--skip-footer", "3"]) == 0
    lines = capsys.readouterr().out.splitlines()
    start = lines.index("- Delimiter: semicolon") + 1
    assert lines[start : start + 2] == [
        "- Skipped lines: 2 (before the header)",
        "- Skipped footer: 3 records (after the data)",
    ]


def test_detection_leaves_the_footer_out(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(ERP), delimiter="auto", skip_footer=1)
    assert (report.delimiter, report.delimiter_detected, report.rows) == (";", True, 4)


def test_detection_fails_with_a_footer_hint(write_csv: WriteCsv) -> None:
    with pytest.raises(DelimiterDetectionError) as info:
        profile_file(write_csv(ERP), delimiter="auto")
    assert info.value.message == (
        "cannot detect the delimiter: no separator gives the same number of fields "
        "on every line; pass it explicitly with --delimiter; if the file ends with 1 footer "
        "line after the data, skip it with --skip-footer 1 (add one for each totals row "
        "above it)"
    )


def test_detection_hint_for_several_lines(write_csv: WriteCsv) -> None:
    with pytest.raises(DelimiterDetectionError) as info:
        profile_file(write_csv("a;b\n1;2\nTotal\n\nFin\n"), delimiter="auto")
    assert info.value.message.endswith(
        "if the file ends with 2 footer lines after the data, skip them with "
        "--skip-footer 2 (add one for each totals row above them)"
    )


def test_no_detection_hint_once_a_footer_is_skipped(write_csv: WriteCsv) -> None:
    # Too few skipped: detection still fails, without a second suggestion.
    with pytest.raises(DelimiterDetectionError) as info:
        profile_file(write_csv("a;b\n1;2\nTotal\nFin\n"), delimiter="auto", skip_footer=1)
    assert info.value.message.endswith("pass it explicitly with --delimiter")
    assert info.value.__cause__ is None  # the original error, not chained to itself


def test_a_title_detection_hint_wins(write_csv: WriteCsv) -> None:
    with pytest.raises(DelimiterDetectionError, match="--skip-lines 1$"):
        profile_file(write_csv("Reporte\na;b\n1;2\n"), delimiter="auto")


def _ragged_near_the_sample_end() -> str:
    """A file longer than the sample whose last complete sampled lines include a ragged one.

    Lines are 1,000 characters long, so the sample holds fewer than
    ``SNIFF_RECORDS`` records and its last lines are judged. Leaving out the
    sample's last lines would hide the ragged one, but it is data, not a footer:
    the file goes on after the sample.
    """
    row = "x" * 997 + ";1\n"
    fitting = (SNIFF_CHARS - 4) // len(row)  # complete rows within the sample
    rows = [row] * (fitting + 50)
    rows[fitting - 2] = "y" * 999 + "\n"  # one field: the second-last complete row
    return "a;b\n" + "".join(rows)


def test_no_detection_hint_when_the_sample_is_not_the_whole_file(write_csv: WriteCsv) -> None:
    path = write_csv(_ragged_near_the_sample_end())
    with pytest.raises(DelimiterDetectionError) as info:
        profile_file(path, delimiter="auto")
    assert info.value.message.endswith("pass it explicitly with --delimiter")
    # The footer is past the sample: nothing in the sample says it is one.
    rows = "".join(f"{i};{i}\n" for i in range(SNIFF_CHARS // 4))
    with pytest.raises(DelimiterDetectionError) as info:
        profile_file(write_csv("a;b\n1\n" + rows + "Fin\n"), delimiter="auto")
    assert info.value.message.endswith("pass it explicitly with --delimiter")
    # The same lines, whole in the sample, get the hint.
    with pytest.raises(DelimiterDetectionError, match="--skip-footer 1"):
        profile_file(write_csv("a;b\n1;2\nFin\n"), delimiter="auto")


def test_only_a_whole_file_sample_leaves_lines_out(write_csv: WriteCsv) -> None:
    # The sample's last lines are data when the file goes on after it.
    path = write_csv(_ragged_near_the_sample_end())
    with pytest.raises(DelimiterDetectionError):
        profile_file(path, delimiter="auto", skip_footer=5)


def test_a_long_file_is_detected_with_its_footer_skipped(write_csv: WriteCsv) -> None:
    # Longer than the sample: the footer is never sampled, so nothing is left out.
    rows = "".join(f"{i};{i}\n" for i in range(SNIFF_CHARS // 4))
    report = profile_file(write_csv("a;b\n" + rows + "Fin\n"), delimiter="auto", skip_footer=1)
    assert (report.delimiter, report.rows) == (";", SNIFF_CHARS // 4)


@pytest.mark.parametrize(
    ("text", "count", "expected"),
    [
        ("h\n1\n2\n", 1, "h\n1\n"),
        ("h\n1\n\n2\n\n", 1, "h\n1\n\n"),
        ("h\n1\n2\n", 2, "h\n"),
        ("h\n1\n2\n", 5, "h\n"),  # the header is kept
        ("\nh\n1\n", 5, "\nh\n"),
        ("h\n", 1, "h\n"),
        ("", 1, ""),
        ("h\n1\n", 0, "h\n1\n"),
        ("h\r\n1\r2\n", 1, "h\r\n1\r"),
    ],
)
def test_without_last_lines(text: str, count: int, expected: str) -> None:
    assert _without_last_lines(text, count) == expected


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("a;b\n1;2\nFin\n", 1),
        ("a;b\n1;2\nTotal\n\nFin\n", 2),
        ("a;b\n1;2\n", None),  # nothing to drop: it already parses
        ("a;b\nFin\n", None),  # only the header would be left
        ("a\n1\nx;y\n", None),  # one column left: not a delimiter
        ("a;b\n1;2\n3,4,5\n6\n", 2),
    ],
)
def test_footer_lines(sample: str, expected: int | None) -> None:
    assert footer_lines(sample) == expected


def test_footer_lines_up_to_the_limit() -> None:
    body = "a;b\n1;2\n3;4\n"
    assert footer_lines(body + "x\n" * MAX_FOOTER_LINES) == MAX_FOOTER_LINES
    assert footer_lines(body + "x\n" * (MAX_FOOTER_LINES + 1)) is None


def test_footer_lines_keeps_a_data_line() -> None:
    # Two non-blank lines (header and one footer line): dropping it leaves only the
    # header, which detection cannot judge, so there is no suggestion.
    assert footer_lines("a;b\nx\n") is None
    with pytest.raises(DelimiterDetectionError):
        detect_delimiter("a;b\nx\n")


@pytest.mark.parametrize(
    ("data", "count", "message"),
    [
        ("a;b\n", 1, "has 0 records after the header, fewer than the 1 skipped"),
        ("a;b\n1;2\n\n", 2, "has 1 record after the header, fewer than the 2 skipped"),
        ("a;b\n1;2\n3;4\n", 3, "has 2 records after the header, fewer than the 3 skipped"),
    ],
)
def test_too_few_records(write_csv: WriteCsv, data: str, count: int, message: str) -> None:
    with pytest.raises(EmptyFileError, match=message + " by --skip-footer$"):
        profile_file(write_csv(data), delimiter=";", skip_footer=count)


def test_exactly_the_footer_leaves_no_data(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("a;b\nTotal\nFin\n"), delimiter=";", skip_footer=2)
    assert (report.rows, report.skipped_footer) == (0, 2)


def test_too_few_records_is_exit_code_5(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write_csv("a;b\n1;2\n", "x.csv")), "--skip-footer", "4"]) == 5
    err = capsys.readouterr().err
    assert err.endswith(
        "x.csv' has 1 record after the header, fewer than the 4 skipped by --skip-footer\n"
    )


def test_an_encoding_error_in_the_footer_is_still_raised(write_csv: WriteCsv) -> None:
    data = b"a;b\n1;2\n" + "Generado: año 2026\n".encode("cp1252")
    with pytest.raises(EncodingError, match="invalid byte at offset 19"):
        profile_file(write_csv(data), delimiter=";", skip_footer=1)
    assert profile_file(write_csv(data), delimiter=";", skip_footer=1, encoding="cp1252").rows == 1


def test_standard_input_and_gzip(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.BufferedReader(io.BytesIO(gzip.compress(ERP.encode())))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(buffer, encoding="utf-8"))
    report = profile_file(Path("-"), delimiter="auto", skip_footer=3)
    assert (report.compressed, report.skipped_footer, report.delimiter, report.rows) == (
        True,
        3,
        ";",
        2,
    )


@pytest.mark.parametrize(("max_rows", "rows", "truncated"), [(1, 1, True), (2, 2, False)])
def test_max_rows_counts_data_rows_only(
    write_csv: WriteCsv, max_rows: int, rows: int, truncated: bool
) -> None:
    report = profile_file(write_csv(ERP), delimiter=";", skip_footer=3, max_rows=max_rows)
    assert (report.rows, report.truncated) == (rows, truncated)


def test_a_truncated_read_never_reaches_the_footer(write_csv: WriteCsv) -> None:
    # Too few records would fail at the end, but --max-rows stops before it.
    data = "a;b\n1;2\n3;4\n"
    report = profile_file(write_csv(data), delimiter=";", skip_footer=1, max_rows=0)
    assert (report.rows, report.truncated) == (0, True)


def test_in_memory_and_streaming_agree(write_csv: WriteCsv) -> None:
    path = write_csv(ERP)
    table = read_table(path, delimiter=";", skip_footer=3)
    assert table.skipped_footer == 3
    assert table.rows == [
        ["05/10/2026", "Ferretería Sur", "1.234,50"],
        ["06/10/2026", "Agro Norte", "980,00"],
    ]
    assert build_report(table) == profile_file(path, delimiter=";", skip_footer=3)
    with open_rows(path, delimiter=";", skip_footer=3) as stream:
        assert stream.skipped_footer == 3 and len(list(stream)) == 2


def test_rows_are_streamed() -> None:
    # Each row comes out as soon as N later records were read, not at the end.
    pulled: list[int] = []

    def numbered() -> Iterator[tuple[list[str], int]]:
        for i in range(5):
            pulled.append(i)
            yield [str(i)], i + 2

    rows = _before_footer(numbered(), 2, "x.csv")
    assert next(rows) == (["0"], 2)
    assert pulled == [0, 1, 2]
    assert list(rows) == [(["1"], 3), (["2"], 4)]


def test_memory_is_bounded_by_the_footer(write_csv: WriteCsv, tmp_path: Path) -> None:
    path = tmp_path / "big.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("a;b\n")
        handle.writelines(f"{i};{'x' * 50}\n" for i in range(50_000))
    tracemalloc.start()
    try:
        with open_rows(path, delimiter=";", skip_footer=10) as stream:
            assert sum(1 for _ in stream) == 49_990
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2_000_000  # 50,000 rows held would take several megabytes


def test_a_negative_count_is_refused(write_csv: WriteCsv) -> None:
    with pytest.raises(ValueError, match="skip_footer must be >= 0, got -1"):
        with open_rows(write_csv("a\n1\n"), skip_footer=-1):
            pass  # pragma: no cover - never reached


@pytest.mark.parametrize(("value", "error"), [("-1", "must be >= 0"), ("x", "invalid integer")])
def test_invalid_values_are_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], value: str, error: str
) -> None:
    with pytest.raises(SystemExit) as info:
        main([str(write_csv("a\n1\n")), "--skip-footer", value])
    assert info.value.code == 2
    assert f"argument --skip-footer: {error}" in capsys.readouterr().err
