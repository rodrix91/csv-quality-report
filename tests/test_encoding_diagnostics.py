"""Actionable UTF-8 decoding errors without changing the selected codec."""

from __future__ import annotations

import gzip
import io
import sys
from pathlib import Path

import pytest

import csv_quality_report.reader as reader
from csv_quality_report.errors import EncodingError
from csv_quality_report.reader import _invalid_utf8_details, _unicode_export_hint, read_table


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        (b"\xff\xfe\x00\x00" + b"s\x00\x00\x00", "UTF-32 byte order mark"),
        (b"\x00\x00\xfe\xff" + b"\x00\x00\x00s", "UTF-32 byte order mark"),
        (b"\xff\xfe" + b"s\x00k\x00", "UTF-16 byte order mark"),
        (b"\xfe\xff" + b"\x00s\x00k", "UTF-16 byte order mark"),
        ("sku;qty\n".encode("utf-32-le"), "UTF-32-LE without a BOM"),
        ("sku;qty\n".encode("utf-32-be"), "UTF-32-BE without a BOM"),
        ("sku;qty\n".encode("utf-16-le"), "UTF-16-LE without a BOM"),
        ("sku;qty\n".encode("utf-16-be"), "UTF-16-BE without a BOM"),
    ],
)
def test_unicode_export_hints_without_guessing_encoding(prefix: bytes, expected: str) -> None:
    hint = _unicode_export_hint(prefix)
    assert hint is not None and expected in hint
    assert "--encoding" in hint


def test_no_unicode_hint_for_plain_bytes_or_short_prefix() -> None:
    assert _unicode_export_hint(b"sku;qty\n1;3\n") is None
    assert _unicode_export_hint(b"s\x00k\x00") is None
    assert _unicode_export_hint(b"") is None


@pytest.mark.parametrize(
    ("codec", "expected"),
    [
        ("utf-16-le", "UTF-16-LE without a BOM"),
        ("utf-16-be", "UTF-16-BE without a BOM"),
        ("utf-32-le", "UTF-32-LE without a BOM"),
        ("utf-32-be", "UTF-32-BE without a BOM"),
        ("utf-16", "UTF-16 byte order mark"),
        ("utf-32", "UTF-32 byte order mark"),
    ],
)
def test_unicode_exports_give_explicit_codec_hints(
    tmp_path: Path, codec: str, expected: str
) -> None:
    source = tmp_path / "export.csv"
    source.write_bytes("sku;qty\nPeñaflor;2\n".encode(codec))
    with pytest.raises(EncodingError) as error:
        read_table(source, delimiter=";")
    assert expected in error.value.message
    assert "invalid byte at offset" in error.value.message
    assert error.value.exit_code == 4
    # The caller must explicitly select the encoding; the reader never guesses.
    assert read_table(source, delimiter=";", encoding=codec).rows[0][0] == "Peñaflor"


@pytest.mark.parametrize(
    ("newlines", "offset", "line"),
    [
        (b"header\nrow\n", 11, 3),
        (b"header\r\nrow\r\n", 13, 3),
        (b"header\rrow\r", 11, 3),
        (b"header\r\nrow\n", 12, 3),
    ],
)
@pytest.mark.parametrize("compressed", [False, True])
def test_invalid_byte_and_line_respect_newline_style_and_gzip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    newlines: bytes,
    offset: int,
    line: int,
    compressed: bool,
) -> None:
    # A short chunk tests CRLF across buffer boundaries and offset scanning.
    monkeypatch.setattr(reader, "_CHUNK", 2)
    raw = newlines + b"\xf1;2\n"
    assert len(newlines) == offset
    path = tmp_path / ("x.csv.gz" if compressed else "x.csv")
    path.write_bytes(gzip.compress(raw) if compressed else raw)
    details = _invalid_utf8_details(path, compressed, offset)
    assert details == f", line {line}: 0xF1, which is 'ñ' in cp1252"
    with pytest.raises(EncodingError) as error:
        read_table(path, delimiter=";")
    message = error.value.message
    assert f"invalid byte at offset {offset}" in message
    if compressed:
        assert "of the decompressed data" in message
    assert details in message


def test_invalid_cp1252_undefined_byte_has_no_false_character_hint(tmp_path: Path) -> None:
    path = tmp_path / "undefined.csv"
    path.write_bytes(b"sku\n\x81\n")
    with pytest.raises(EncodingError) as error:
        read_table(path)
    assert "line 2: 0x81" in error.value.message
    assert "which is" not in error.value.message


def test_stdin_keeps_original_no_offset_diagnostic(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = io.BytesIO(b"sku\n\xff\n")
    wrapped = io.TextIOWrapper(io.BufferedReader(raw), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", wrapped)
    with pytest.raises(EncodingError) as error:
        read_table(Path("-"))
    assert "offset of the invalid byte is not available on standard input" in error.value.message
    assert "0xFF" not in error.value.message
    assert "line 2" not in error.value.message


def test_explicit_encoding_failure_keeps_existing_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "bad-cp1252.csv"
    path.write_bytes(b"sku\n\x81\n")
    with pytest.raises(EncodingError) as error:
        read_table(path, encoding="cp1252")
    assert "is not valid cp1252 (invalid byte at offset 4)" in error.value.message
    assert "check the encoding given with --encoding" in error.value.message
    assert "line 2" not in error.value.message
