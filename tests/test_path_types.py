"""The reading API accepts str and path-like paths, not only pathlib.Path (issue #98)."""

from __future__ import annotations

import gzip
import io
import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import CsvQualityError, profile_file, read_table
from csv_quality_report.errors import EXIT_IO, FileReadError
from csv_quality_report.reader import open_rows

WriteCsv = Callable[..., Path]
DATA = "id;peso;fecha\n1;12,5;2026-10-01\n2;;2026-10-02\n2;;2026-10-02\n"


class PathLike(os.PathLike[str]):
    """A path-like object that is not a pathlib.Path."""

    def __init__(self, path: Path) -> None:
        self._path = str(path)

    def __fspath__(self) -> str:
        return self._path


def test_str_and_path_like_give_the_same_report(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    expected = profile_file(path, delimiter="auto", decimal_comma=True)
    assert profile_file(str(path), delimiter="auto", decimal_comma=True) == expected
    assert profile_file(PathLike(path), delimiter="auto", decimal_comma=True) == expected
    assert (expected.rows, expected.duplicate_rows) == (3, 1)


def test_read_table_and_open_rows_take_str(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    assert read_table(str(path), delimiter=";") == read_table(path, delimiter=";")
    with open_rows(str(path), delimiter=";") as stream:
        assert stream.path == path  # still a Path for the rest of the reader
        assert stream.header == ["id", "peso", "fecha"]
        assert len(list(stream)) == 3


def test_gzip_file_as_str(write_csv: WriteCsv) -> None:
    path = write_csv(gzip.compress(DATA.encode()), "data.csv.gz")
    report = profile_file(str(path), delimiter="auto", decimal_comma=True)
    assert (report.compressed, report.rows) == (True, 3)


def test_dash_as_str_reads_standard_input(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.BufferedReader(io.BytesIO(DATA.encode()))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(buffer, encoding="utf-8"))
    report = profile_file("-", delimiter="auto", decimal_comma=True)
    assert report.rows == 3


def test_missing_file_as_str_is_a_read_error(tmp_path: Path) -> None:
    missing = str(tmp_path / "nope.csv")
    with pytest.raises(FileReadError) as excinfo:
        profile_file(missing)
    assert isinstance(excinfo.value, CsvQualityError)
    assert excinfo.value.exit_code == EXIT_IO
    assert f"cannot read '{missing}'" in excinfo.value.message
