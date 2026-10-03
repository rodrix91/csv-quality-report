"""Read a CSV file into memory, failing with clear errors."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from .errors import EmptyFileError, EncodingError, FileReadError, RaggedRowError


@dataclass(frozen=True)
class Table:
    """A parsed CSV: header plus data rows (all cells are strings)."""

    header: list[str]
    rows: list[list[str]]
    truncated: bool  # True when --max-rows stopped reading early


def read_table(path: Path, max_rows: int | None = None) -> Table:
    """Read ``path`` as UTF-8 (a leading BOM is accepted).

    Raises a ``CsvQualityError`` subclass for unreadable files, invalid UTF-8,
    empty files and rows whose cell count differs from the header's.
    Fully blank lines are skipped. At most ``max_rows`` data rows are read.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FileReadError(f"cannot read '{path}': {exc.strerror or exc}") from exc

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise EncodingError(
            f"'{path}' is not valid UTF-8 (invalid byte at offset {exc.start}); "
            "re-save the file as UTF-8"
        ) from exc

    reader = csv.reader(io.StringIO(text, newline=""))
    header: list[str] | None = None
    rows: list[list[str]] = []
    truncated = False
    try:
        for record in reader:
            if not record:  # blank line
                continue
            if header is None:
                header = record
                continue
            if max_rows is not None and len(rows) >= max_rows:
                truncated = True
                break
            if len(record) != len(header):
                raise RaggedRowError(
                    f"row at line {reader.line_num} has {len(record)} fields, "
                    f"expected {len(header)} (from the header)"
                )
            rows.append(record)
    except csv.Error as exc:
        raise RaggedRowError(f"malformed CSV near line {reader.line_num}: {exc}") from exc

    if header is None:
        raise EmptyFileError(f"'{path}' is empty (no header row)")
    return Table(header=header, rows=rows, truncated=truncated)
