"""Regression tests for UTF-8 failures that reject more than one input byte."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

import csv_quality_report.reader as reader
from csv_quality_report.errors import EncodingError
from csv_quality_report.reader import read_table


@pytest.mark.parametrize(
    ("bad", "diagnosis"),
    [
        (b"\xe2\x82x\n", "0xE2 0x82, which is 'â‚' in cp1252"),
        (b"\xe2\x82", "0xE2 0x82, which is 'â‚' in cp1252"),
        (b"\xf0\x9f\x98", "0xF0 0x9F 0x98, which is 'ðŸ˜' in cp1252"),
        (b"\xc3(\n", "0xC3, which is 'Ã' in cp1252"),
    ],
)
@pytest.mark.parametrize("compressed", [False, True])
def test_diagnostics_name_every_rejected_byte(
    tmp_path: Path,
    bad: bytes,
    diagnosis: str,
    compressed: bool,
) -> None:
    raw = b"col\n" + bad
    path = tmp_path / ("broken.csv.gz" if compressed else "broken.csv")
    path.write_bytes(gzip.compress(raw) if compressed else raw)
    with pytest.raises(EncodingError) as exc:
        read_table(path)
    message = exc.value.message
    assert exc.value.exit_code == 4
    assert "invalid byte at offset 4" in message
    assert "line 2: " + diagnosis in message
    assert ("of the decompressed data" in message) is compressed


def test_rejected_sequence_spanning_decode_chunks_is_reported_in_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The first read ends with the three-byte sequence's lead byte;
    # incremental decoding reports it after the next read.
    monkeypatch.setattr(reader, "_CHUNK", 5)
    source = tmp_path / "split.csv"
    source.write_bytes(b"col\n\xe2\x82x\n")
    assert reader._invalid_utf8_offset(source) == 4
    with pytest.raises(EncodingError) as exc:
        read_table(source)
    assert "offset 4, line 2: 0xE2 0x82, which is 'â‚' in cp1252" in exc.value.message


def test_undefined_cp1252_byte_stays_without_character_hint(tmp_path: Path) -> None:
    source = tmp_path / "undefined.csv"
    source.write_bytes(b"col\n\x81x\n")
    with pytest.raises(EncodingError) as exc:
        read_table(source)
    assert "offset 4, line 2: 0x81" in exc.value.message
    assert "which is" not in exc.value.message
