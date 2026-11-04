"""What the UTF-8 error says about the bytes it rejected (#266).

The encoding is never guessed, but the message names the bytes, their line
and how cp1252 reads them, and recognizes UTF-16 and UTF-32 files, so the
``--encoding`` to use is clear before running again.
"""

from __future__ import annotations

import codecs
import gzip
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import reader
from csv_quality_report.cli import main
from csv_quality_report.errors import EncodingError
from csv_quality_report.profile import profile_file

WriteCsv = Callable[..., Path]
TEXT = "Cliente\tMonto\nPeña\t1,5\nJosé\t2\n"
GENERIC = (
    "re-save the file as UTF-8, or name its encoding with --encoding "
    "(spreadsheet exports are often cp1252)"
)


def message(path: Path, **options: object) -> str:
    with pytest.raises(EncodingError) as excinfo:
        profile_file(path, **options)  # type: ignore[arg-type]
    assert excinfo.value.exit_code == 4
    return excinfo.value.message


def test_cp1252_byte_with_its_line_and_reading(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("Cliente;Monto\nAna;1\nPeña;1,5\n".encode("cp1252"))
    assert main([str(path)]) == 4
    assert capsys.readouterr().err == (
        f"error: '{path}' is not valid UTF-8 (invalid byte at offset 22, line 3: 0xF1, "
        f"which is 'ñ' in cp1252); {GENERIC}\n"
    )


@pytest.mark.parametrize("end", [b"\n", b"\r\n", b"\r"])
def test_lines_end_with_lf_crlf_or_a_lone_cr(write_csv: WriteCsv, end: bytes) -> None:
    data = end.join([b"Cliente", b"Ana", b"Jos\xe9", b""])
    offset = data.index(b"\xe9")
    assert f"offset {offset}, line 3: 0xE9, which is 'é' in cp1252);" in message(write_csv(data))


def test_gzip_offsets_and_lines_count_the_decompressed_data(write_csv: WriteCsv) -> None:
    path = write_csv(gzip.compress(b"name\n" + "José\n".encode("latin-1")), "lat.csv.gz")
    assert message(path).endswith(
        "(invalid byte at offset 8 of the decompressed data, line 2: 0xE9, "
        f"which is 'é' in cp1252); {GENERIC}"
    )


def test_a_byte_cp1252_does_not_define_has_no_reading(write_csv: WriteCsv) -> None:
    assert message(write_csv(b"a\n\x81\n")).endswith(
        f"(invalid byte at offset 2, line 2: 0x81); {GENERIC}"
    )


def test_every_rejected_byte_is_shown(write_csv: WriteCsv) -> None:
    # A truncated three-byte sequence: UTF-8 rejects both bytes at once.
    assert "line 2: 0xE2 0x82, which is 'â‚' in cp1252);" in message(write_csv(b"a\n\xe2\x82x\n"))


def test_an_invisible_reading_is_escaped(write_csv: WriteCsv) -> None:
    # 0xA0 is a no-break space in cp1252, invisible if printed as is.
    assert "0xA0, which is '\\xa0' in cp1252);" in message(write_csv(b"a\n1\xa0000\n"))


@pytest.mark.parametrize(
    ("mark", "codec", "label", "advice"),
    [
        (codecs.BOM_UTF16_LE, "utf-16-le", "UTF-16", "utf-16"),  # Excel's "Unicode Text"
        (codecs.BOM_UTF16_BE, "utf-16-be", "UTF-16", "utf-16"),
        (codecs.BOM_UTF32_LE, "utf-32-le", "UTF-32", "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32-be", "UTF-32", "utf-32"),
    ],
)
def test_a_byte_order_mark_names_the_encoding(
    write_csv: WriteCsv, mark: bytes, codec: str, label: str, advice: str
) -> None:
    data = mark + TEXT.encode(codec)
    path = write_csv(data)
    assert message(path).endswith(
        f": the file starts with a {label} byte order mark); "
        f"name its encoding with --encoding {advice}, or re-save the file as UTF-8"
    )
    # The advice works.
    report = profile_file(path, delimiter="auto", encoding=advice)
    assert (report.rows, report.columns[0].name) == (2, "Cliente")


@pytest.mark.parametrize("codec", ["utf-16-le", "utf-16-be"])
def test_utf16_without_a_byte_order_mark(write_csv: WriteCsv, codec: str) -> None:
    path = write_csv(TEXT.encode(codec))
    assert message(path).endswith(
        f": every second byte of the first 8 is NUL, as in {codec.upper()} without a "
        f"byte order mark); name its encoding with --encoding {codec}, "
        "or re-save the file as UTF-8"
    )
    report = profile_file(path, delimiter="auto", encoding=codec)
    assert (report.rows, report.columns[0].name) == (2, "Cliente")


@pytest.mark.parametrize(
    "data",
    [
        b"a\x00\xff\x00",  # too short to tell, though it reads as UTF-16-LE
        b"a\x00b\x00\x00\x00c\x00\xff\n",  # a NUL in the other half too
        b"\x00a\x00\x00\x00b\x00c\xff\n",
        b"a\x00b\x00c\x00dd\xff\n",  # not every second byte is NUL
        b"\x00a\x00bc\x00\x00d\xff\n",
    ],
)
def test_other_nul_bytes_do_not_suggest_utf16(write_csv: WriteCsv, data: bytes) -> None:
    text = message(write_csv(data))
    assert "NUL" not in text
    assert text.endswith(GENERIC)


@pytest.mark.parametrize("size", range(1, 9))
def test_line_ends_split_across_read_chunks(
    write_csv: WriteCsv, monkeypatch: pytest.MonkeyPatch, size: int
) -> None:
    # Small reads put a CRLF across a chunk boundary for some sizes.
    monkeypatch.setattr(reader, "_CHUNK", size)
    data = b"a\r\n\r\nb\r\n\xff\n"
    found = reader._find_invalid(write_csv(data))
    assert (found.offset, found.line, found.rejected) == (len(data) - 2, 4, b"\xff")


def test_a_sequence_started_in_the_previous_chunk(
    write_csv: WriteCsv, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The first read ends with 0xC3, a lead byte UTF-8 holds back; the next
    # read starts with "(", so the rejected byte is in the previous chunk.
    monkeypatch.setattr(reader, "_CHUNK", 5)
    found = reader._find_invalid(write_csv(b"x\nab\xc3(\n\nz\n"))
    assert (found.offset, found.line, found.rejected, found.head) == (4, 2, b"\xc3", b"x\nab\xc3")


def test_offset_helper_still_gives_the_offset(write_csv: WriteCsv) -> None:
    assert reader._invalid_utf8_offset(write_csv(b"ab\n\xff\n")) == 3
