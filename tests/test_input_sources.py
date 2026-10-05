"""Tests for standard input (``-``, issue #26) and gzip input (issue #27)."""

from __future__ import annotations

import gzip
import io
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.errors import EncodingError, FileReadError
from csv_quality_report.profile import build_report, profile_file
from csv_quality_report.reader import SNIFF_CHARS, STDIN_NAME, display_name, is_stdin, read_table

WriteCsv = Callable[..., Path]
DATA = "sku;price;city\nA1;10,5;La Paz\nB2;7,25;Tarija\nA1;10,5;La Paz\n"
ROOT = Path(__file__).resolve().parent.parent


def feed_stdin(monkeypatch: pytest.MonkeyPatch, data: bytes) -> io.BufferedReader[io.BytesIO]:
    """Replace sys.stdin with a text stream over ``data`` and return its buffer."""
    buffer = io.BufferedReader(io.BytesIO(data))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(buffer, encoding="utf-8"))
    return buffer


def run_json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert main([*args, "--format", "json"]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


# --- standard input -----------------------------------------------------------


def test_stdin_helpers() -> None:
    assert is_stdin(Path("-")) and not is_stdin(Path("data.csv"))
    assert display_name(Path("-")) == STDIN_NAME == "<stdin>"
    assert display_name(Path("dir/data.csv")) == "dir/data.csv"


def test_stdin_report_matches_the_file_report(
    write_csv: WriteCsv, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(DATA)
    from_file = run_json(capsys, str(path), "--delimiter", ";")
    feed_stdin(monkeypatch, DATA.encode())
    from_stdin = run_json(capsys, "-", "--delimiter", ";")
    assert from_stdin.pop("source") == "<stdin>"
    from_file.pop("source")
    assert from_stdin == from_file
    assert from_stdin["duplicate_rows"] == 1


def test_stdin_is_not_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = feed_stdin(monkeypatch, DATA.encode())
    report = profile_file(Path("-"), delimiter=";")
    assert report.rows == 3
    assert not buffer.closed


def test_auto_detection_on_stdin_without_seeking(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed_stdin(monkeypatch, DATA.encode())
    rep = run_json(capsys, "-", "--delimiter", "auto", "--decimal-comma")
    assert (rep["delimiter"], rep["delimiter_detected"], rep["rows"]) == (";", True, 3)
    assert rep["columns"][1]["type"] == "float"


@pytest.mark.parametrize("cut", [SNIFF_CHARS - 3, SNIFF_CHARS, SNIFF_CHARS + 2])
def test_detection_sample_boundary_does_not_split_a_row(
    monkeypatch: pytest.MonkeyPatch, cut: int
) -> None:
    # Build a stream whose detection sample ends near the middle of a row, and
    # check that every row is parsed whole after detection hands over.
    header = "id;note\n"
    filler_row = "1;" + "x" * 50 + "\n"
    body = filler_row * (cut // len(filler_row) + 3)
    data = (header + body).encode()
    feed_stdin(monkeypatch, data)
    report = profile_file(Path("-"), delimiter="auto")
    assert report.delimiter == ";"
    assert report.rows == body.count("\n")
    assert report.columns[1].distinct == 1


def test_quoted_newline_across_the_detection_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    # The detection sample (SNIFF_CHARS + 1 characters, then the rest of that
    # line) ends inside a quoted field that contains a newline, so the record
    # continues in the stream after the hand-over.
    header = "id;comment\n"
    rows = (SNIFF_CHARS - 5 - len(header)) // 5
    head = header + "1;ok\n" * rows
    assert len(head) == SNIFF_CHARS - 5
    quoted_start = len(head) + 3  # after '2;"'
    assert quoted_start < SNIFF_CHARS + 1 < quoted_start + len("first line")
    data = head + '2;"first line\nsecond line"\n3;done\n'
    feed_stdin(monkeypatch, data.encode())
    report = profile_file(Path("-"), delimiter="auto")
    assert (report.delimiter, report.rows) == (";", rows + 2)
    assert report.columns[1].top_values == [
        ("ok", rows),
        ("first line\nsecond line", 1),
        ("done", 1),
    ]


def test_stdin_encoding_error_says_offset_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed_stdin(monkeypatch, "name\nJosé\n".encode("latin-1"))
    assert main(["-"]) == 4
    err = capsys.readouterr().err
    assert err == (
        "error: '<stdin>' is not valid UTF-8 (the offset of the invalid byte is not "
        "available on standard input); re-save the file as UTF-8, or name its encoding "
        "with --encoding (spreadsheet exports are often cp1252)\n"
    )


def test_empty_stdin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    feed_stdin(monkeypatch, b"")
    assert main(["-"]) == 5
    assert capsys.readouterr().err == "error: '<stdin>' is empty (no header row)\n"


def test_stdin_from_a_real_pipe(cli_env: dict[str, str]) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "csv_quality_report", "-", "--delimiter", "auto"],
        input=DATA.encode(),
        env=cli_env,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.decode()
    assert out.startswith("# CSV quality report: <stdin>\n")
    assert "- Delimiter: semicolon (detected)\n" in out


# --- gzip ---------------------------------------------------------------------


def test_gzip_file_matches_the_plain_file(write_csv: WriteCsv) -> None:
    plain = profile_file(write_csv(DATA, "data.csv"), delimiter=";")
    packed = profile_file(write_csv(gzip.compress(DATA.encode()), "data.csv.gz"), delimiter=";")
    assert packed.compressed and not plain.compressed
    assert packed.columns == plain.columns
    assert (packed.rows, packed.duplicate_rows) == (plain.rows, plain.duplicate_rows)


def test_gzip_is_detected_by_content_not_by_name(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(gzip.compress(DATA.encode()), "export.csv"), delimiter=";")
    assert report.compressed and report.rows == 3


def test_gzip_with_bom_and_auto_detection(write_csv: WriteCsv) -> None:
    path = write_csv(gzip.compress(b"\xef\xbb\xbf" + DATA.encode()), "bom.csv.gz")
    report = profile_file(path, delimiter="auto")
    assert (report.delimiter, report.columns[0].name) == (";", "sku")


def test_gzip_on_stdin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    feed_stdin(monkeypatch, gzip.compress(DATA.encode()))
    rep = run_json(capsys, "-", "--delimiter", ";")
    assert (rep["compressed"], rep["rows"], rep["source"]) == (True, 3, "<stdin>")


def test_in_memory_table_records_compression(write_csv: WriteCsv) -> None:
    path = write_csv(gzip.compress(DATA.encode()), "data.csv.gz")
    table = read_table(path, delimiter=";")
    assert table.compressed
    assert build_report(table) == profile_file(path, delimiter=";")


def test_markdown_names_the_compression(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write_csv(gzip.compress(b"a,b\n1,2\n"), "x.csv.gz"))]) == 0
    assert "- Compression: gzip\n" in capsys.readouterr().out
    assert main([str(write_csv("a,b\n1,2\n"))]) == 0
    assert "Compression" not in capsys.readouterr().out


def test_invalid_byte_offset_counts_decompressed_data(write_csv: WriteCsv) -> None:
    path = write_csv(gzip.compress(b"name\n" + "José\n".encode("latin-1")), "lat.csv.gz")
    with pytest.raises(EncodingError) as excinfo:
        profile_file(path)
    assert "invalid byte at offset 8 of the decompressed data" in excinfo.value.message


def test_invalid_byte_in_gzip_found_during_detection(write_csv: WriteCsv) -> None:
    path = write_csv(gzip.compress("id;n\n1;José\n".encode("latin-1")), "lat.csv.gz")
    with pytest.raises(EncodingError) as excinfo:
        profile_file(path, delimiter="auto")
    assert "invalid byte at offset 10 of the decompressed data" in excinfo.value.message


@pytest.mark.parametrize("auto", [False, True])
def test_truncated_gzip_is_a_read_error(write_csv: WriteCsv, auto: bool) -> None:
    packed = gzip.compress(("a,b\n" + "1,2\n" * 5000).encode())
    path = write_csv(packed[: len(packed) // 2], "cut.csv.gz")
    with pytest.raises(FileReadError) as excinfo:
        profile_file(path, delimiter="auto" if auto else ",")
    assert excinfo.value.message.startswith(f"cannot read '{path}': ")


@pytest.mark.parametrize("auto", [False, True])
def test_corrupt_gzip_header_is_a_read_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], auto: bool
) -> None:
    path = write_csv(b"\x1f\x8b" + b"\x00" * 30, "bad.csv.gz")
    args = [str(path)] + (["--delimiter", "auto"] if auto else [])
    assert main(args) == 3
    assert capsys.readouterr().err.startswith(f"error: cannot read '{path}': ")


def test_corrupt_deflate_data_is_a_read_error(write_csv: WriteCsv) -> None:
    packed = bytearray(gzip.compress(("a,b\n" + "1,2\n" * 2000).encode()))
    packed[20:40] = b"\xff" * 20  # damage the compressed body, keep the header
    with pytest.raises(FileReadError):
        profile_file(write_csv(bytes(packed), "damaged.csv.gz"))


def test_example_files_report_not_compressed() -> None:
    assert not profile_file(ROOT / "examples" / "tiny.csv").compressed
