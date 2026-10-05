"""Tests for the single-pass, streaming profile path (issue #4)."""

from __future__ import annotations

import csv
import random
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from csv_quality_report.cli import main
from csv_quality_report.errors import DelimiterDetectionError, EncodingError, RaggedRowError
from csv_quality_report.profile import (
    _BATCH_ROWS,
    _row_digest,
    build_report,
    profile_file,
    profile_rows,
)
from csv_quality_report.reader import _CHUNK, detect_delimiter, open_rows, read_table

WriteCsv = Callable[..., Path]
ROOT = Path(__file__).resolve().parent.parent


def _random_csv(rows: int, seed: int) -> str:
    rng = random.Random(seed)
    lines = ["id,city,amount,flag,day,note"]
    for _ in range(rows):
        if rng.random() < 0.02 and len(lines) > 1:
            lines.append(rng.choice(lines[1:]))  # exact duplicate of an earlier row
            continue
        lines.append(
            ",".join(
                [
                    str(rng.randint(1, rows // 2 + 1)),
                    rng.choice(["La Paz", "Tarija", "Jujuy", "", " Salta "]),
                    rng.choice([f"{rng.uniform(-50, 500):.2f}", "", "7"]),
                    rng.choice(["true", "false", "TRUE", ""]),
                    f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                    rng.choice(["ok", '"a, quoted; note"', "", "x" * rng.randint(1, 5)]),
                ]
            )
        )
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    ("rows", "seed"),
    [(0, 1), (1, 2), (37, 3), (_BATCH_ROWS - 1, 4), (_BATCH_ROWS, 5), (2 * _BATCH_ROWS + 7, 6)],
)
def test_streaming_matches_in_memory_report(write_csv: WriteCsv, rows: int, seed: int) -> None:
    path = write_csv(_random_csv(rows, seed))
    assert profile_file(path) == build_report(read_table(path))


@pytest.mark.parametrize("max_rows", [1, _BATCH_ROWS, _BATCH_ROWS + 1])
def test_streaming_matches_in_memory_with_max_rows(write_csv: WriteCsv, max_rows: int) -> None:
    path = write_csv(_random_csv(_BATCH_ROWS + 50, 9))
    streamed = profile_file(path, max_rows=max_rows)
    assert streamed == build_report(read_table(path, max_rows=max_rows))
    assert streamed.rows == max_rows
    assert streamed.truncated


def test_example_files_match_in_memory_report() -> None:
    for name in ("sample.csv", "tiny.csv"):
        path = ROOT / "examples" / name
        assert profile_file(path) == build_report(read_table(path))


def test_duplicates_are_found_across_batches() -> None:
    header = ["a", "b"]
    rows = [[str(i), "x"] for i in range(_BATCH_ROWS + 10)]
    rows.append(["3", "x"])  # repeats row 3, which sits in the first batch
    rows.append([str(_BATCH_ROWS + 5), "x"])  # repeats a row of the second batch
    result = profile_rows(header, iter(rows))
    assert (result.rows, result.duplicate_rows) == (_BATCH_ROWS + 12, 2)


def test_profile_rows_consumes_a_generator_lazily() -> None:
    produced = 0

    def gen() -> Iterator[list[str]]:
        nonlocal produced
        for i in range(25_000):
            produced += 1
            yield [str(i % 10)]

    result = profile_rows(["n"], gen())
    assert produced == 25_000
    assert result.rows == 25_000
    assert result.duplicate_rows == 25_000 - 10
    assert result.columns[0].distinct == 10


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (["a,b"], ["a", "b"]),
        (["ab", ""], ["a", "b"]),
        (["", "ab"], ["ab", ""]),
        (["1,1:ab"], ["1", "1"]),
        ([":"], ["", ""]),
        (["a"], ["a", ""]),
    ],
)
def test_row_digest_keeps_cell_boundaries(left: list[str], right: list[str]) -> None:
    assert _row_digest(left) != _row_digest(right)


def test_row_digest_is_deterministic() -> None:
    assert _row_digest(["La Paz", "", "1"]) == _row_digest(["La Paz", "", "1"])
    assert len(_row_digest(["x"])) == 16


def test_missing_cells_are_not_counted_as_values(write_csv: WriteCsv) -> None:
    path = write_csv("a,b\n,1\n  ,2\n,3\n")
    col = profile_file(path).columns[0]
    assert (col.missing, col.distinct, col.top_values, col.type) == (3, 0, [], "string")


# --- encoding errors while streaming ----------------------------------------


def test_invalid_byte_offset_counts_the_bom(write_csv: WriteCsv) -> None:
    # BOM (3 bytes) + "a\n" (2 bytes): the bad byte is at file offset 5.
    path = write_csv(b"\xef\xbb\xbfa\n\xff\n")
    with pytest.raises(EncodingError) as excinfo:
        profile_file(path)
    assert "invalid byte at offset 5" in excinfo.value.message


def test_invalid_byte_offset_beyond_the_first_chunk(write_csv: WriteCsv) -> None:
    filler = b"v\n" + b"1\n" * (_CHUNK // 2 + 100)  # longer than one read chunk
    path = write_csv(filler + b"\xc3(\n")
    with pytest.raises(EncodingError) as excinfo:
        profile_file(path)
    assert f"invalid byte at offset {len(filler)}" in excinfo.value.message


def test_multibyte_character_split_across_chunks_is_valid(write_csv: WriteCsv) -> None:
    # Place "ñ" (2 bytes) so that it straddles the chunk boundary, then a bad byte.
    head = b"v\n" + b"a" * (_CHUNK - 3) + b"\n"
    assert len(head) == _CHUNK
    data = head[:-1] + "ñ".encode() + b"\n\xff\n"
    path = write_csv(data)
    with pytest.raises(EncodingError) as excinfo:
        profile_file(path)
    assert f"invalid byte at offset {len(data) - 2}" in excinfo.value.message


def test_bad_bytes_after_max_rows_are_not_read(write_csv: WriteCsv) -> None:
    # Streaming stops at the limit, so bytes far beyond it are never decoded.
    path = write_csv(b"v\n1\n2\n" + b"3\n" * 100_000 + b"\xff\n")
    report = profile_file(path, max_rows=2)
    assert (report.rows, report.truncated) == (2, True)


def test_cli_still_reports_encoding_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("name\nJosé\n".encode("latin-1"))
    assert main([str(path)]) == 4
    assert "invalid byte at offset 8" in capsys.readouterr().err


# --- other reader behavior --------------------------------------------------


def test_bom_and_auto_detection_together(write_csv: WriteCsv) -> None:
    path = write_csv(b"\xef\xbb\xbfid;city\n1;La Paz\n")
    report = profile_file(path, delimiter="auto")
    assert [c.name for c in report.columns] == ["id", "city"]
    assert (report.delimiter, report.delimiter_detected) == (";", True)


def test_ragged_row_error_is_raised_while_streaming(write_csv: WriteCsv) -> None:
    body = "a,b\n" + "1,2\n" * (_BATCH_ROWS + 5) + "3\n"
    path = write_csv(body)
    with pytest.raises(RaggedRowError) as excinfo:
        profile_file(path)
    assert f"row at line {_BATCH_ROWS + 7} has 1 fields" in excinfo.value.message


def test_file_is_closed_after_an_error(write_csv: WriteCsv) -> None:
    path = write_csv("a,b\n1,2\n3\n")
    with pytest.raises(RaggedRowError), open_rows(path) as stream:
        list(stream)
    # On every platform the handle must be closed: re-opening for writing works.
    path.write_text("ok\n", encoding="utf-8")
    assert profile_file(path).rows == 0


# --- malformed input and detection edge cases --------------------------------


def test_field_over_the_csv_size_limit_is_a_malformed_csv_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    huge = "x" * (csv.field_size_limit() + 1)
    path = write_csv(f"a,b\n1,{huge}\n")
    assert main([str(path)]) == 6
    assert "malformed CSV near line 2" in capsys.readouterr().err


def test_detection_survives_samples_that_do_not_parse() -> None:
    # Lower the csv field limit so a field inside the 64 KiB sample exceeds it:
    # every candidate then fails to parse and detection must say so cleanly.
    previous = csv.field_size_limit(100)
    try:
        with pytest.raises(DelimiterDetectionError) as excinfo:
            detect_delimiter("a;b\n1;" + "x" * 200 + "\n")
    finally:
        csv.field_size_limit(previous)
    assert "no separator gives the same number of fields" in excinfo.value.message


def test_oversized_field_beyond_the_sample_does_not_affect_detection() -> None:
    huge = "x" * (csv.field_size_limit() + 1)
    assert detect_delimiter(f"a;b\n1;{huge}\n") == ";"


def test_detection_ignores_blank_lines() -> None:
    assert detect_delimiter("\n\na;b\n\n1;2\n\n") == ";"


def test_auto_detection_reports_encoding_errors_with_offset(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("id;name\n1;José\n".encode("latin-1"))
    assert main([str(path), "--delimiter", "auto"]) == 4
    assert "invalid byte at offset 13" in capsys.readouterr().err
