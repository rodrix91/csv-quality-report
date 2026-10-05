"""Read a CSV file into memory, failing with clear errors."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from .errors import (
    DelimiterDetectionError,
    EmptyFileError,
    EncodingError,
    FileReadError,
    RaggedRowError,
)

DELIMITER_AUTO = "auto"
DELIMITER_CANDIDATES = (",", ";", "\t", "|")
SNIFF_CHARS = 64 * 1024  # how much text detection looks at
SNIFF_RECORDS = 100  # how many lines detection checks
DELIMITER_NAMES = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}


@dataclass(frozen=True)
class Table:
    """A parsed CSV: header plus data rows (all cells are strings)."""

    header: list[str]
    rows: list[list[str]]
    truncated: bool  # True when --max-rows stopped reading early
    delimiter: str = ","
    delimiter_detected: bool = False  # True when chosen by ``detect_delimiter``


def dedupe_header(header: list[str]) -> list[str]:
    """Make column names unique: later repeats get ``_2``, ``_3``, ... suffixes.

    ``["a", "a", "a"]`` becomes ``["a", "a_2", "a_3"]``. A suffixed name that
    would collide with another existing name keeps counting up.
    """
    seen: set[str] = set(header)
    used: set[str] = set()
    result: list[str] = []
    for name in header:
        if name not in used:
            used.add(name)
            result.append(name)
            continue
        n = 2
        while f"{name}_{n}" in used or f"{name}_{n}" in seen:
            n += 1
        new = f"{name}_{n}"
        used.add(new)
        result.append(new)
    return result


def _record_widths(sample: str, delimiter: str) -> set[int] | None:
    """Field counts of the first records of ``sample``; ``None`` if it does not parse."""
    widths: set[int] = set()
    reader = csv.reader(io.StringIO(sample, newline=""), delimiter=delimiter)
    try:
        for record in reader:
            if not record:
                continue
            widths.add(len(record))
            if len(widths) > 1 or reader.line_num >= SNIFF_RECORDS:
                break
    except csv.Error:
        return None
    return widths


def delimiter_name(delimiter: str) -> str:
    """Readable name for a delimiter: ``tab``, ``semicolon``... or the character itself."""
    return DELIMITER_NAMES.get(delimiter, delimiter)


def detect_delimiter(text: str) -> str:
    """Pick the field separator of ``text`` among ``, ; tab |``.

    A candidate qualifies when every record in the first ``SNIFF_RECORDS``
    lines (within ``SNIFF_CHARS`` characters) has the same number of fields,
    and that number is greater than one. Exactly one qualifying candidate is
    returned. A file where every candidate gives a single field is a
    one-column file and gets ``,``. Anything else (no candidate or several)
    raises ``DelimiterDetectionError`` instead of guessing.
    """
    sample = text[:SNIFF_CHARS]
    if len(text) > SNIFF_CHARS and "\n" in sample:
        sample = sample[: sample.rindex("\n")]  # never judge a cut-off last line

    qualifying: list[str] = []
    single_column = True
    for candidate in DELIMITER_CANDIDATES:
        widths = _record_widths(sample, candidate)
        if widths is None or len(widths) > 1:
            single_column = False
            continue
        if widths and next(iter(widths)) > 1:
            qualifying.append(candidate)
            single_column = False

    if len(qualifying) == 1:
        return qualifying[0]
    if not qualifying and single_column:
        return ","
    if qualifying:
        names = ", ".join(delimiter_name(c) for c in qualifying)
        reason = f"several separators fit every line ({names})"
    else:
        reason = "no separator gives the same number of fields on every line"
    raise DelimiterDetectionError(
        f"cannot detect the delimiter: {reason}; pass it explicitly with --delimiter"
    )


def read_table(path: Path, max_rows: int | None = None, delimiter: str = ",") -> Table:
    """Read ``path`` as UTF-8 (a leading BOM is accepted).

    ``delimiter`` is the single character that separates fields (default ``,``),
    or ``"auto"`` to choose it with ``detect_delimiter``.

    Raises a ``CsvQualityError`` subclass for unreadable files, invalid UTF-8,
    empty files and rows whose cell count differs from the header's.
    Fully blank lines are skipped. Duplicate column names are made unique
    with ``_2``, ``_3`` suffixes (see ``dedupe_header``). At most ``max_rows`` data rows are read.
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

    detected = delimiter == DELIMITER_AUTO
    if detected:
        delimiter = detect_delimiter(text)

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
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
    return Table(
        header=dedupe_header(header),
        rows=rows,
        truncated=truncated,
        delimiter=delimiter,
        delimiter_detected=detected,
    )
