"""Read a CSV file, lazily or into memory, failing with clear errors."""

from __future__ import annotations

import codecs
import csv
import gzip
import io
import re
import sys
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Protocol, cast

from .errors import (
    DelimiterDetectionError,
    EmptyFileError,
    EncodingError,
    FileReadError,
    RaggedRowError,
)

_CHUNK = 1 << 20  # bytes per read when locating an invalid UTF-8 byte
DELIMITER_AUTO = "auto"
STDIN = "-"  # path that means "read standard input"
DEFAULT_ENCODING = "utf-8"  # read as utf-8-sig, so a leading BOM is accepted
STDIN_NAME = "<stdin>"  # how standard input is named in messages and reports
_GZIP_MAGIC = b"\x1f\x8b"  # first bytes of every gzip stream; CSV text never starts so
# Errors a (possibly compressed) byte stream can raise while it is being read.
_STREAM_ERRORS = (OSError, EOFError, zlib.error)
DELIMITER_CANDIDATES = (",", ";", "\t", "|")
SNIFF_CHARS = 64 * 1024  # how much text detection looks at
SNIFF_RECORDS = 100  # how many lines detection checks
DELIMITER_NAMES = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}
# Excel's hint line, e.g. "sep=;": one separator character, optionally quoted.
_SEP_LINE_RE = re.compile(r'"?sep=([^"\r\n])"?(?:\r\n|\r|\n)?', re.IGNORECASE)


@dataclass(frozen=True)
class Table:
    """A parsed CSV: header plus data rows (all cells are strings)."""

    header: list[str]
    rows: list[list[str]]
    truncated: bool  # True when --max-rows stopped reading early
    delimiter: str = ","
    delimiter_detected: bool = False  # True when chosen by ``detect_delimiter``
    compressed: bool = False  # True when the input was gzip-compressed
    encoding: str = DEFAULT_ENCODING  # normalized codec name used to decode the input
    sep_line: bool = False  # True when a first line such as "sep=;" was skipped


def declared_delimiter(line: str) -> str | None:
    """The separator declared by an Excel ``sep=`` line (``sep=;`` gives ``;``), else ``None``.

    The whole line must be the declaration: ``sep=``, in any case, one
    character and an optional line end, optionally inside double quotes.
    """
    match = _SEP_LINE_RE.fullmatch(line)
    return None if match is None else match.group(1)


class _LineCounter:
    """The ``line_num`` of a csv reader plus lines read before it started."""

    def __init__(self, reader: _CsvReader, skipped: int) -> None:
        self._reader = reader
        self._skipped = skipped

    @property
    def line_num(self) -> int:
        return self._reader.line_num + self._skipped


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


def _describe(delimiter: str) -> str:
    """``semicolon``, ``tab``... or the quoted character, for messages."""
    return DELIMITER_NAMES.get(delimiter, repr(delimiter))


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
        compressed: bool = False,
        encoding: str = DEFAULT_ENCODING,
        sep_line: bool = False,
    ) -> None:
        self.path = path
        self.compressed = compressed
        self.encoding = encoding
        self.sep_line = sep_line
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
        for record in _guarded(
            self.path, self._records, self._reader, self.compressed, self.encoding
        ):
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


def is_stdin(path: Path) -> bool:
    """True when ``path`` is ``-``, the conventional name for standard input."""
    return str(path) == STDIN


def display_name(path: Path) -> str:
    """Name used for ``path`` in messages and reports (``<stdin>`` for ``-``)."""
    return STDIN_NAME if is_stdin(path) else str(path)


def normalize_encoding(name: str) -> str:
    """Canonical name of a text codec (``latin-1`` gives ``iso8859-1``).

    Raises ``LookupError`` for unknown names and for codecs that do not decode
    bytes to text, such as ``base64`` or ``rot13``.
    """
    canonical = codecs.lookup(name).name
    # Check it the way it is used: TextIOWrapper rejects non-text codecs with
    # LookupError ("... is not a text encoding"). bytes.decode does not, for
    # empty input.
    io.TextIOWrapper(io.BytesIO(), encoding=canonical)
    return canonical


def _invalid_utf8_offset(
    path: Path, compressed: bool = False, encoding: str = DEFAULT_ENCODING
) -> int:
    """Byte offset (from the start of the file) of the first byte ``encoding`` rejects.

    Named for UTF-8, the default, but works for any text codec. Decodes in
    chunks so it works on files of any size. For a gzip file the offset is
    counted in the decompressed data. Only called after a decoding error was
    seen, so a valid file returning 0 does not happen in practice.
    """
    decoder = codecs.getincrementaldecoder(encoding)()
    consumed = 0
    with gzip.open(path, "rb") if compressed else path.open("rb") as handle:
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


def _guarded(
    path: Path,
    records: Iterator[list[str]],
    reader: _CsvReader,
    compressed: bool = False,
    encoding: str = DEFAULT_ENCODING,
) -> Iterator[list[str]]:
    """Re-raise low-level errors from ``records`` as ``CsvQualityError`` subclasses."""
    try:
        yield from records
    except UnicodeDecodeError as exc:
        raise _encoding_error(path, compressed, encoding) from exc
    except csv.Error as exc:
        message = f"malformed CSV near line {reader.line_num}: {exc}"
        if "field larger than field limit" in str(exc):
            message += "; if the file really has long fields, raise the limit with --max-field-size"
        raise RaggedRowError(message) from exc
    except _STREAM_ERRORS as exc:  # I/O failure, or corrupt or truncated gzip data
        raise _read_error(path, exc) from exc


def _read_error(path: Path, exc: BaseException) -> FileReadError:
    reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else exc
    return FileReadError(f"cannot read '{display_name(path)}': {reason}")


def _encoding_error(
    path: Path, compressed: bool = False, encoding: str = DEFAULT_ENCODING
) -> EncodingError:
    if is_stdin(path):
        where = "the offset of the invalid byte is not available on standard input"
    else:
        offset = _invalid_utf8_offset(path, compressed, encoding)
        where = f"invalid byte at offset {offset}"
        if compressed:
            where += " of the decompressed data"
    if encoding == DEFAULT_ENCODING:
        advice = (
            "re-save the file as UTF-8, or name its encoding with --encoding "
            "(spreadsheet exports are often cp1252)"
        )
        label = "UTF-8"
    else:
        advice = "check the encoding given with --encoding"
        label = encoding
    return EncodingError(f"'{display_name(path)}' is not valid {label} ({where}); {advice}")


@contextmanager
def _text_stream(
    path: Path, encoding: str = DEFAULT_ENCODING
) -> Iterator[tuple[io.TextIOWrapper, bool]]:
    """Open ``path`` (or standard input for ``-``) as text in ``encoding``.

    UTF-8 is read as ``utf-8-sig``, so a leading byte order mark is accepted.

    Yields the text stream and whether the input was gzip-compressed, which is
    detected from the first two bytes, so ``.csv.gz`` files and compressed
    pipes need no flag. Standard input is never closed.
    """
    owned = not is_stdin(path)
    try:
        binary = path.open("rb") if owned else cast(io.BufferedReader, sys.stdin.buffer)
        compressed = binary.peek(2)[:2] == _GZIP_MAGIC
    except OSError as exc:
        raise _read_error(path, exc) from exc
    try:
        source = gzip.GzipFile(fileobj=binary, mode="rb") if compressed else binary
        codec = "utf-8-sig" if encoding == DEFAULT_ENCODING else encoding
        text = io.TextIOWrapper(cast(io.BufferedReader, source), encoding=codec, newline="")
        try:
            yield text, compressed
        finally:
            if owned or compressed:
                text.close()  # closing a GzipFile leaves its fileobj open
            else:
                text.detach()  # keep standard input usable
    finally:
        if owned:
            binary.close()


@contextmanager
def open_rows(
    path: Path,
    max_rows: int | None = None,
    delimiter: str = ",",
    encoding: str = DEFAULT_ENCODING,
    max_field_size: int | None = None,
) -> Iterator[RowStream]:
    """Open ``path`` and yield a ``RowStream`` that reads it lazily.

    The file is read as UTF-8 (a leading BOM is accepted), or in ``encoding``
    (a canonical codec name, see ``normalize_encoding``), without loading it
    into memory. ``-`` reads standard input, and gzip-compressed input is
    decompressed on the fly (detected from its first bytes). ``delimiter`` is
    one character, or ``"auto"`` to choose it with ``detect_delimiter`` from
    the first ``SNIFF_CHARS`` characters; detection never seeks, so it also
    works on pipes.

    Errors are ``CsvQualityError`` subclasses: unreadable file, invalid UTF-8,
    empty file (raised here), and ragged or malformed rows (raised while
    iterating, in the order they appear in the file). Fully blank lines are
    skipped. Duplicate column names get ``_2``, ``_3`` suffixes.

    A first line such as ``sep=;`` (Excel's hint, see ``declared_delimiter``)
    is skipped and recorded in ``sep_line``. With ``"auto"`` the declared
    separator is used without sampling; any other delimiter must match it,
    or ``DelimiterDetectionError`` is raised instead of reading the file with
    the wrong one. Line numbers in errors still count the skipped line.

    ``max_field_size`` raises Python's ``csv`` field size limit (131,072
    characters by default) while the file is read. The limit is process-wide
    in the ``csv`` module, so the previous value is restored when the stream
    closes, also after an error.
    """
    previous_limit = None if max_field_size is None else csv.field_size_limit(max_field_size)
    try:
        with _open_rows(path, max_rows, delimiter, encoding) as stream:
            yield stream
    finally:
        if previous_limit is not None:
            csv.field_size_limit(previous_limit)


@contextmanager
def _open_rows(
    path: Path, max_rows: int | None, delimiter: str, encoding: str
) -> Iterator[RowStream]:
    """``open_rows`` without the field size handling."""
    with _text_stream(path, encoding) as (handle, compressed):
        try:
            first = handle.readline()
            declared = declared_delimiter(first)
            if declared is not None:
                first = ""  # a declaration, not data
                if delimiter == DELIMITER_AUTO:
                    delimiter = declared
                elif delimiter != declared:
                    raise DelimiterDetectionError(
                        f"'{display_name(path)}' declares the {_describe(declared)} delimiter "
                        f"in its first line (sep={declared}), but the delimiter in use is "
                        f"{_describe(delimiter)}; pass --delimiter auto to follow the file"
                    )
            detected = delimiter == DELIMITER_AUTO
            sample = first
            if detected and len(first) <= SNIFF_CHARS:
                sample += handle.read(SNIFF_CHARS + 1 - len(first))
                if len(sample) > SNIFF_CHARS:
                    sample += handle.readline()  # end the sample on a line boundary
        except UnicodeDecodeError as exc:
            raise _encoding_error(path, compressed, encoding) from exc
        except _STREAM_ERRORS as exc:
            raise _read_error(path, exc) from exc
        if detected:
            delimiter = detect_delimiter(sample)
        # Parse what was read ahead again, then continue with the rest of the stream.
        lines = chain(io.StringIO(sample, newline=""), handle)

        reader = csv.reader(lines, delimiter=delimiter)
        records = iter(reader)
        counter = _LineCounter(reader, 0 if declared is None else 1)
        header = next(
            (r for r in _guarded(path, records, counter, compressed, encoding) if r), None
        )
        if header is None:
            raise EmptyFileError(f"'{display_name(path)}' is empty (no header row)")
        yield RowStream(
            path,
            records,
            counter,
            header,
            max_rows,
            delimiter,
            detected,
            compressed,
            encoding,
            sep_line=declared is not None,
        )


def read_table(
    path: Path,
    max_rows: int | None = None,
    delimiter: str = ",",
    encoding: str = DEFAULT_ENCODING,
    max_field_size: int | None = None,
) -> Table:
    """Read the whole of ``path`` into a ``Table`` (see ``open_rows`` for the rules).

    Convenient for small files and tests; the CLI streams with ``open_rows``
    instead, so it does not hold all rows in memory.
    """
    with open_rows(
        path,
        max_rows=max_rows,
        delimiter=delimiter,
        encoding=encoding,
        max_field_size=max_field_size,
    ) as stream:
        rows = list(stream)
        return Table(
            header=stream.header,
            rows=rows,
            truncated=stream.truncated,
            delimiter=stream.delimiter,
            delimiter_detected=stream.delimiter_detected,
            compressed=stream.compressed,
            encoding=stream.encoding,
            sep_line=stream.sep_line,
        )
