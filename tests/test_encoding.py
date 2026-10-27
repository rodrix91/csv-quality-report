"""Tests for ``--encoding`` (issue #47)."""

from __future__ import annotations

import csv
import gzip
import io
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.errors import EncodingError
from csv_quality_report.profile import build_report, profile_file
from csv_quality_report.reader import DEFAULT_ENCODING, normalize_encoding, read_table

WriteCsv = Callable[..., Path]
TEXT = "ciudad;peso\nAsunción;10,5\nPeñaflor;7,25\nSão Paulo;3\n"
OPTS = ("--delimiter", ";", "--decimal-comma")


def run_json(path: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *OPTS, *extra]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


def test_spreadsheet_export_in_cp1252(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = run_json(write_csv(TEXT.encode("cp1252")), capsys, "--encoding", "cp1252")
    assert rep["encoding"] == "cp1252"
    assert [t["value"] for t in rep["columns"][0]["top_values"]] == [
        "Asunción",
        "Peñaflor",
        "São Paulo",
    ]
    assert rep["columns"][1]["type"] == "float"


def test_same_report_as_the_utf8_file(write_csv: WriteCsv) -> None:
    utf8 = profile_file(write_csv(TEXT, "a.csv"), delimiter=";")
    latin = profile_file(
        write_csv(TEXT.encode("latin-1"), "b.csv"), delimiter=";", encoding="iso8859-1"
    )
    assert latin.columns == utf8.columns and latin.encoding == "iso8859-1"


@pytest.mark.parametrize(
    ("name", "canonical"),
    [("latin-1", "iso8859-1"), ("CP1252", "cp1252"), ("UTF8", "utf-8"), ("utf_16", "utf-16")],
)
def test_names_are_normalized(name: str, canonical: str) -> None:
    assert normalize_encoding(name) == canonical


@pytest.mark.parametrize("name", ["base64", "rot13", "zlib", "no-such-codec"])
def test_unknown_and_non_text_codecs_are_rejected(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    with pytest.raises(LookupError):
        normalize_encoding(name)
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv("a\n1\n")), "--encoding", name])
    assert excinfo.value.code == 2
    assert "invalid --encoding value" in capsys.readouterr().err


def test_utf16_with_bom_and_auto_detection(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(TEXT.encode("utf-16")), delimiter="auto", encoding="utf-16")
    assert (report.delimiter, report.rows) == (";", 3)
    assert report.columns[0].name == "ciudad"


@pytest.mark.parametrize("compressed", [False, True])
def test_utf16_without_bom_is_controlled_encoding_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], compressed: bool, tmp_path: Path
) -> None:
    raw = TEXT.encode("utf-16-le")  # valid UTF-16 code units but missing the required BOM
    source = gzip.compress(raw) if compressed else raw
    path = write_csv(source, "missing-bom.csv.gz" if compressed else "missing-bom.csv")
    with pytest.raises(EncodingError, match="is not valid utf-16") as info:
        read_table(path, encoding="utf-16", delimiter="auto")
    assert info.value.exit_code == 4
    assert (
        "invalid byte at offset 0" in info.value.message
        or "UTF-16 stream does not start with BOM" in info.value.message
    )
    assert "check the encoding given with --encoding" in info.value.message

    previous = tmp_path / "existing-report.json"
    previous.write_text('{"preserved": true}\n', encoding="utf-8")
    assert main([
        str(path), "--encoding", "utf-16", "--delimiter", "auto",
        "--json-output", str(previous)
    ]) == 4
    err = capsys.readouterr().err
    assert "is not valid utf-16" in err
    assert ("invalid byte at offset 0" in err or "UTF-16 stream does not start with BOM" in err)
    assert "Traceback" not in err
    assert previous.read_text(encoding="utf-8") == '{"preserved": true}\n'


def test_later_plain_unicode_error_is_normalized_by_row_guard() -> None:
    # The header setup and row iterator have separate error boundaries.
    # Exercise the iterator boundary without relying on TextIOWrapper buffering.
    from csv_quality_report.reader import _guarded

    def faulty_rows() -> Iterator[list[str]]:
        yield ["ok"]
        raise UnicodeError("codec stream state invalid")

    rows = _guarded(
        Path("sample.csv"), faulty_rows(), csv.reader(io.StringIO("sample\n")),
        encoding="utf-16",
    )
    assert next(rows) == ["ok"]
    with pytest.raises(EncodingError, match="codec stream state invalid") as info:
        next(rows)
    assert info.value.exit_code == 4
    assert "check the encoding given with --encoding" in info.value.message


def test_gzip_and_stdin_with_an_encoding(
    write_csv: WriteCsv, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    packed = gzip.compress(TEXT.encode("cp1252"))
    assert profile_file(write_csv(packed, "x.csv.gz"), delimiter=";", encoding="cp1252").compressed
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BufferedReader(io.BytesIO(packed))))
    rep = run_json(Path("-"), capsys, "--encoding", "cp1252")
    assert (rep["source"], rep["compressed"], rep["rows"]) == ("<stdin>", True, 3)


def test_utf8_error_points_to_the_option(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(TEXT.encode("cp1252"))
    assert main([str(path), *OPTS]) == 4
    err = capsys.readouterr().err
    assert "is not valid UTF-8 (invalid byte at offset 18); re-save the file as UTF-8" in err
    assert "name its encoding with --encoding (spreadsheet exports are often cp1252)" in err


def test_invalid_byte_for_the_chosen_encoding(write_csv: WriteCsv) -> None:
    # 0x81 is undefined in cp1252, at offset 4 after "a\n1\n".
    with pytest.raises(EncodingError) as excinfo:
        profile_file(write_csv(b"a\n1\n\x81\n"), encoding="cp1252")
    assert excinfo.value.message.endswith(
        "is not valid cp1252 (invalid byte at offset 4); check the encoding given with --encoding"
    )


def test_latin1_never_fails_on_any_byte(write_csv: WriteCsv) -> None:
    data = b"v\n" + bytes(b for b in range(256) if b not in b'\r\n,"') + b"\n"
    assert profile_file(write_csv(data), encoding="iso8859-1").rows == 1


def test_markdown_line_only_for_non_default_encodings(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(TEXT.encode("cp1252"))
    assert main([str(path), *OPTS, "--encoding", "cp1252"]) == 0
    assert "- Encoding: cp1252\n" in capsys.readouterr().out
    assert main([str(write_csv(TEXT)), *OPTS, "--encoding", "utf-8"]) == 0
    assert "Encoding" not in capsys.readouterr().out


def test_default_report_names_utf8(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv("a\n1\n")).encoding == DEFAULT_ENCODING == "utf-8"


def test_streaming_and_in_memory_agree(write_csv: WriteCsv) -> None:
    path = write_csv(TEXT.encode("cp1252"))
    streamed = profile_file(path, delimiter=";", encoding="cp1252")
    assert streamed == build_report(read_table(path, delimiter=";", encoding="cp1252"))
