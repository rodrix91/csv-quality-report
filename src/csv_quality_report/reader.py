"""Read a CSV file, lazily or into memory, failing with clear errors."""

from __future__ import annotations

import codecs
import csv
import io
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .errors import (
    DelimiterDetectionError,
    EmptyFileError,
    EncodingError,
    FileReadError,
    RaggedRowError,
)

_CHUNK = 1 << 20  # bytes per read when locating an invalid UTF-8 byte
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


class RowStream:
    """Validated data rows of an open CSV file, produced one at a time.

    Iterate it once. Each row has exactly ``len(header)`` cells. ``truncated``
    becomes ``True`` when ``max_rows`` stopped reading before the end of the
    file; it is only meaningful after iteration has finished.
    """

    def __init__(
        self,
        path: Path,
        records: Iterator[list[str]],
        reader: _CsvReader,
        raw_header: list[str],
        max_rows: int | None,
        delimiter: str,
        delimiter_detected: bool,
    ) -> None:
        self.path = path
        self.header = dedupe_header(raw_header)
        self.delimiter = delimiter
        self.delimiter_detected = delimiter_detected
        self.truncated = False
        self._records = records
        self._reader = reader
        self._width = len(raw_header)
        self._max_rows = max_rows

    def __iter__(self) -> Iterator[list[str]]:
        count = 0
        for record in _guarded(self.path, self._records, self._reader):
            if not record:  # blank line
                continue
            if self._max_rows is not None and count >= self._max_rows:
                self.truncated = True
                return
            if len(record) != self._width:
                raise RaggedRowError(
                    f"row at line {self._reader.line_num} has {len(record)} fields, "
                    f"expected {self._width} (from the header)"
                )
            count += 1
            yield record


class _CsvReader(Protocol):
    @property
    def line_num(self) -> int: ...


def _invalid_utf8_offset(path: Path) -> int:
    """Byte offset (from the start of the file) of the first invalid UTF-8 byte.

    Decodes in chunks so it works on files of any size. Only called after a
    decoding error was seen, so a valid file returning 0 does not happen in practice.
    """
    decoder = codecs.getincrementaldecoder("utf-8")()
    consumed = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            pending = len(decoder.getstate()[0])
            try:
                decoder.decode(chunk, final=not chunk)
            except UnicodeDecodeError as exc:
                return consumed - pending + exc.start
            if not chunk:  # pragma: no cover - only called after a decoding error
                return 0
            consumed += len(chunk)


def _guarded(path: Path, records: Iterator[list[str]], reader: _CsvReader) -> Iterator[list[str]]:
    """Re-raise low-level errors from ``records`` as ``CsvQualityError`` subclasses."""
    try:
        yield from records
    except UnicodeDecodeError as exc:
        raise _encoding_error(path) from exc
    except csv.Error as exc:
        raise RaggedRowError(f"malformed CSV near line {reader.line_num}: {exc}") from exc
    except OSError as exc:  # pragma: no cover - I/O failure mid-read (e.g. lost mount)
        raise FileReadError(f"cannot read '{path}': {exc.strerror or exc}") from exc


def _encoding_error(path: Path) -> EncodingError:
    return EncodingError(
        f"'{path}' is not valid UTF-8 (invalid byte at offset {_invalid_utf8_offset(path)}); "
        "re-save the file as UTF-8"
    )


@contextmanager
def open_rows(path: Path, max_rows: int | None = None, delimiter: str = ",") -> Iterator[RowStream]:
    """Open ``path`` and yield a ``RowStream`` that reads it lazily.

    The file is read as UTF-8 (a leading BOM is accepted) without loading it
    into memory. ``delimiter`` is one character, or ``"auto"`` to choose it
    with ``detect_delimiter`` from the first ``SNIFF_CHARS`` characters.

    Errors are ``CsvQualityError`` subclasses: unreadable file, invalid UTF-8,
    empty file (raised here), and ragged or malformed rows (raised while
    iterating, in the order they appear in the file). Fully blank lines are
    skipped. Duplicate column names get ``_2``, ``_3`` suffixes.
    """
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise FileReadError(f"cannot read '{path}': {exc.strerror or exc}") from exc
    with handle:
        detected = delimiter == DELIMITER_AUTO
        if detected:
            try:
                sample = handle.read(SNIFF_CHARS + 1)
                handle.seek(0)
            except UnicodeDecodeError as exc:
                raise _encoding_error(path) from exc
            except OSError as exc:  # pragma: no cover - I/O failure mid-read
                raise FileReadError(f"cannot read '{path}': {exc.strerror or exc}") from exc
            delimiter = detect_delimiter(sample)

        reader = csv.reader(handle, delimiter=delimiter)
        records = iter(reader)
        header = next((r for r in _guarded(path, records, reader) if r), None)
        if header is None:
            raise EmptyFileError(f"'{path}' is empty (no header row)")
        yield RowStream(path, records, reader, header, max_rows, delimiter, detected)


def read_table(path: Path, max_rows: int | None = None, delimiter: str = ",") -> Table:
    """Read the whole of ``path`` into a ``Table`` (see ``open_rows`` for the rules).

    Convenient for small files and tests; the CLI streams with ``open_rows``
    instead, so it does not hold all rows in memory.
    """
    with open_rows(path, max_rows=max_rows, delimiter=delimiter) as stream:
        rows = list(stream)
        return Table(
            header=stream.header,
            rows=rows,
            truncated=stream.truncated,
            delimiter=stream.delimiter,
            delimiter_detected=stream.delimiter_detected,
        )
