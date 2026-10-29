"""Read a CSV file, lazily or into memory, failing with clear errors."""

from __future__ import annotations

import codecs
import csv
import gzip
import io
import os
import re
import sys
import zlib
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Protocol, cast

from .errors import (
    CsvQualityError,
    DelimiterDetectionError,
    EmptyFileError,
    EncodingError,
    FileReadError,
    RaggedRowError,
)

_CHUNK = 1 << 20  # bytes per read when locating an invalid UTF-8 byte
DELIMITER_AUTO = "auto"
STDIN = "-"  # path that means "read standard input"
# What the public reading functions accept as a path: "data.csv", Path(...),
# any os.PathLike; "-" means standard input.
PathArg = str | os.PathLike[str]
DEFAULT_ENCODING = "utf-8"  # read as utf-8-sig, so a leading BOM is accepted
STDIN_NAME = "<stdin>"  # how standard input is named in messages and reports
_GZIP_MAGIC = b"\x1f\x8b"  # first bytes of every gzip stream; CSV text never starts so
# Errors a (possibly compressed) byte stream can raise while it is being read.
_STREAM_ERRORS = (OSError, EOFError, zlib.error)
DELIMITER_CANDIDATES = (",", ";", "\t", "|")
SNIFF_CHARS = 64 * 1024  # how much text detection looks at
SNIFF_RECORDS = 100  # how many lines detection checks
MAX_TITLE_LINES = 20  # how many leading title lines a failed detection looks past
MAX_FOOTER_LINES = 20  # how many trailing footer records an error looks for
DELIMITER_NAMES = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}
# Excel's hint line, e.g. "sep=;": one separator character, optionally quoted.
_SEP_LINE_RE = re.compile(r'("?)sep=([^"\r\n])\1(?:\r\n|\r|\n)?', re.IGNORECASE)


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
    skipped_lines: int = 0  # lines skipped before the header (``skip_lines``)
    skipped_footer: int = 0  # records dropped after the data (``skip_footer``)


def declared_delimiter(line: str) -> str | None:
    """The separator declared by an Excel ``sep=`` line (``sep=;`` gives ``;``), else ``None``.

    The whole line must be the declaration: ``sep=``, in any case, one
    character and an optional line end, optionally inside double quotes.
    """
    match = _SEP_LINE_RE.fullmatch(line)
    return None if match is None else match.group(2)


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


def _record_widths(sample: str, delimiter: str, *, strict: bool = True) -> set[int] | None:
    """Field counts of sample records; reject malformed quotes if complete."""
    widths: set[int] = set()
    reader = csv.reader(io.StringIO(sample, newline=""), delimiter=delimiter, strict=strict)
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
    if len(text) > SNIFF_CHARS:
        # Both LF and CR can terminate physical CSV lines (including CRLF).
        # Never judge the final partial line against complete CSV records.
        last_line_end = max(sample.rfind("\n"), sample.rfind("\r"))
        if last_line_end >= 0:
            sample = sample[:last_line_end]

    qualifying: list[str] = []
    single_column = True
    for candidate in DELIMITER_CANDIDATES:
        # When the sniff window truncates a quoted record, postpone strict
        # quote validation until the full file reader processes it.
        widths = _record_widths(sample, candidate, strict=len(text) <= SNIFF_CHARS)
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


def title_lines(sample: str) -> int | None:
    """How many leading lines of ``sample`` to drop for ``detect_delimiter`` to succeed.

    Only called after detection failed on the whole sample. Tries dropping 1
    to ``MAX_TITLE_LINES`` lines, always leaving at least one, and returns the
    first count after which one separator gives the same number of fields
    (more than one) on every line while the dropped lines have no field
    separator, as titles do, or ``None``. It suggests ``--skip-lines``
    for exports that start with title lines (#161).
    """
    lines = io.StringIO(sample, newline="").readlines()  # split like the reader does
    for count in range(1, min(MAX_TITLE_LINES, len(lines) - 1) + 1):
        dropped, rest = "".join(lines[:count]), "".join(lines[count:])
        try:
            delimiter = detect_delimiter(rest)
        except DelimiterDetectionError:
            continue
        widths = _record_widths(rest, delimiter)
        # A one-column rest ("," is then returned) does not count, and the
        # dropped lines must look like titles: no separator, so one field each.
        titles = _record_widths(dropped, delimiter)
        if widths and max(widths) > 1 and titles is not None and titles <= {1}:
            return count
    return None


def _without_last_lines(text: str, count: int) -> str:
    """``text`` without its last ``count`` non-blank lines (and the blank lines among them).

    The first non-blank line, the header, is always kept.
    """
    lines = io.StringIO(text, newline="").readlines()  # split like the reader does
    filled = [i for i, line in enumerate(lines) if line.strip("\r\n")]
    if len(filled) <= 1 or count <= 0:
        return text
    cut = filled[-min(count, len(filled) - 1)]
    return "".join(lines[:cut])


def footer_lines(sample: str) -> int | None:
    """How many trailing non-blank lines of ``sample`` to drop for ``detect_delimiter`` to succeed.

    ``sample`` must hold the whole file. Only called after detection failed
    on it. Tries dropping 1 to ``MAX_FOOTER_LINES`` non-blank lines from the
    end (blank lines among them go too), always leaving at least two, and
    returns the first count after which one separator gives the same number
    of fields (more than one) on every line, or ``None``. It suggests
    ``--skip-footer`` for exports that end with a footer (#192).
    """
    filled = sum(1 for line in io.StringIO(sample, newline="") if line.strip("\r\n"))
    for count in range(1, min(MAX_FOOTER_LINES, filled - 2) + 1):
        rest = _without_last_lines(sample, count)
        try:
            delimiter = detect_delimiter(rest)
        except DelimiterDetectionError:
            continue
        widths = _record_widths(rest, delimiter)
        if widths and max(widths) > 1:  # a one-column rest does not count
            return count
    return None


class RowStream:
    """Validated data rows of an open CSV file, produced one at a time.

    Iterate it once. Each row has exactly ``len(header)`` cells. ``truncated``
    becomes ``True`` when ``max_rows`` stopped reading before the end of the
    file; it is only meaningful after iteration has finished.
    """

    def __init__(
        self,
        path: Path,
        name: str,
        records: Iterator[list[str]],
        reader: _CsvReader,
        raw_header: list[str],
        max_rows: int | None,
        delimiter: str,
        delimiter_detected: bool,
        compressed: bool = False,
        encoding: str = DEFAULT_ENCODING,
        sep_line: bool = False,
        skipped_lines: int = 0,
        skipped_footer: int = 0,
    ) -> None:
        self.path = path
        self.name = name  # the path as given, for messages
        self.compressed = compressed
        self.encoding = encoding
        self.sep_line = sep_line
        self.skipped_lines = skipped_lines
        self.skipped_footer = skipped_footer
        self.header = dedupe_header(raw_header)
        self.delimiter = delimiter
        self.delimiter_detected = delimiter_detected
        self.truncated = False
        self._records = records
        self._reader = reader
        self._width = len(raw_header)
        self._max_rows = max_rows

    def __iter__(self) -> Iterator[list[str]]:
        rows = _guarded(
            self.path, self._records, self._reader, self.compressed, self.encoding, self.name
        )
        # Non-blank records and the line each one ends on, read when it is read.
        numbered: Iterator[tuple[list[str], int]] = (
            (record, self._reader.line_num) for record in rows if record
        )
        if self.skipped_footer:
            numbered = _before_footer(numbered, self.skipped_footer, self.name)
        count = 0
        for record, line in numbered:
            if self._max_rows is not None and count >= self._max_rows:
                self.truncated = True
                return
            if len(record) != self._width:
                raise RaggedRowError(self._ragged_message(record, line, numbered))
            count += 1
            yield record

    def _ragged_message(
        self, record: list[str], line: int, later: Iterator[tuple[list[str], int]]
    ) -> str:
        """The error for ``record``, of the wrong width, with a hint when one fits.

        ``later`` holds the records after it; it may be read to look for a footer.
        """
        message = (
            f"row at line {line} has {len(record)} fields, expected {self._width} (from the header)"
        )
        if self._width == 1 and len(record) > 1 and not self.skipped_lines:
            # The usual symptom of a title line read as the header (#161):
            # this row is then the real header, after the title lines.
            titles = line - 1 - int(self.sep_line)
            message += (
                "; if this row is the header and the lines before it are titles, "
                f"skip them with --skip-lines {titles}"
            )
        elif not self.skipped_footer:
            after = _footer_after(later, self._width)
            if after == 0:
                message += (
                    "; if this last record is a footer, skip it with --skip-footer 1 "
                    "(add one for each totals row above it)"
                )
            elif after is not None:
                message += (
                    f"; if this record and the {after} after it are a footer, skip "
                    f"{'both' if after == 1 else 'them'} with --skip-footer {after + 1} "
                    "(add one for each totals row above them)"
                )
        return message


def _before_footer(
    numbered: Iterator[tuple[list[str], int]], count: int, name: str
) -> Iterator[tuple[list[str], int]]:
    """``numbered`` without its last ``count`` items (``skip_footer``, #192).

    Each item is held until ``count`` more have been read, so memory stays
    ``O(count)``. Raises ``EmptyFileError`` when there are fewer than ``count``.
    """
    held: deque[tuple[list[str], int]] = deque()
    for item in numbered:
        held.append(item)
        if len(held) > count:
            yield held.popleft()
    if len(held) < count:
        records = "record" if len(held) == 1 else "records"
        raise EmptyFileError(
            f"'{name}' has {len(held)} {records} after the header, "
            f"fewer than the {count} skipped by --skip-footer"
        )


def _footer_after(later: Iterator[tuple[list[str], int]], width: int) -> int | None:
    """How many records follow a ragged one when they look like the rest of a footer.

    Reads at most ``MAX_FOOTER_LINES`` - 1 more records. Returns their number
    when the file ends among them and none has the header's ``width`` (so all
    would fail too), else ``None``; also ``None`` when reading them fails.
    """
    after = 0
    try:
        for record, _ in later:
            if after == MAX_FOOTER_LINES - 1 or len(record) == width:
                return None
            after += 1
    except CsvQualityError:
        return None
    return after


class _CsvReader(Protocol):
    @property
    def line_num(self) -> int: ...


def is_stdin(path: PathArg) -> bool:
    """True when ``path`` is ``-``, the conventional name for standard input."""
    return os.fspath(path) == STDIN


def display_name(path: PathArg) -> str:
    """Name used for ``path`` in messages and reports (``<stdin>`` for ``-``).

    A ``str`` is kept exactly as given, so a path typed as ``data/x.csv`` is
    reported as ``data/x.csv`` on every platform, also on Windows, where
    ``Path`` would turn it into ``data\\x.csv`` (#120). A path-like object
    gives its ``os.fspath`` text.
    """
    return STDIN_NAME if is_stdin(path) else os.fspath(path)


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
    name: str | None = None,
) -> Iterator[list[str]]:
    """Re-raise low-level errors from ``records`` as ``CsvQualityError`` subclasses.

    ``name`` is the path as given, for messages (``display_name(path)`` by default).
    """
    if name is None:
        name = display_name(path)
    try:
        yield from records
    except UnicodeDecodeError as exc:
        raise _encoding_error(path, name, compressed, encoding) from exc
    except UnicodeError as exc:
        raise _other_unicode_error(name, encoding, exc) from exc
    except csv.Error as exc:
        message = f"malformed CSV near line {reader.line_num}: {exc}"
        if "field larger than field limit" in str(exc):
            message += "; if the file really has long fields, raise the limit with --max-field-size"
        raise RaggedRowError(message) from exc
    except _STREAM_ERRORS as exc:  # I/O failure, or corrupt or truncated gzip data
        raise _read_error(name, exc) from exc


def _read_error(name: str, exc: BaseException) -> FileReadError:
    reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else exc
    return FileReadError(f"cannot read '{name}': {reason}")


def _encoding_error(
    path: Path, name: str, compressed: bool = False, encoding: str = DEFAULT_ENCODING
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
    return EncodingError(f"'{name}' is not valid {label} ({where}); {advice}")


def _other_unicode_error(name: str, encoding: str, exc: UnicodeError) -> EncodingError:
    """Describe codec errors without byte offsets, e.g. UTF-16 without its BOM.

    Some incremental decoders raise plain UnicodeError instead of
    UnicodeDecodeError. Re-decoding to calculate an offset would raise again,
    so report the codec's actual reason without claiming a byte position.
    """
    return EncodingError(
        f"'{name}' is not valid {encoding} ({exc}); check the encoding given with --encoding"
    )


@contextmanager
def _text_stream(
    path: Path, name: str, encoding: str = DEFAULT_ENCODING
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
        raise _read_error(name, exc) from exc
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
    path: PathArg,
    max_rows: int | None = None,
    delimiter: str = ",",
    encoding: str = DEFAULT_ENCODING,
    max_field_size: int | None = None,
    skip_lines: int = 0,
    skip_footer: int = 0,
) -> Iterator[RowStream]:
    """Open ``path`` and yield a ``RowStream`` that reads it lazily.

    ``path`` is a ``str`` or any path-like object (``pathlib.Path``...).

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

    ``skip_lines`` lines are skipped before the header, for exports that start
    with title lines (#161). They are text lines, not CSV records, and come
    after a ``sep=`` line, which is not counted in them; delimiter detection
    samples the lines after them, and line numbers in errors still count
    them. A file that has no line left for the header raises
    ``EmptyFileError``. A negative ``skip_lines`` raises ``ValueError``.

    ``skip_footer`` records are dropped from the end of the file, for exports
    that end with a footer: totals rows, a record count, a "generated by" line
    (#192). They are CSV records after the header, so blank lines are not
    counted, and they are never checked against the header's width. Each row
    is held until ``skip_footer`` more have been read, so the file is still
    read once, in ``O(skip_footer)`` extra memory. A file with fewer records
    after the header raises ``EmptyFileError`` when the iteration reaches its
    end. With ``"auto"``, when the detection sample holds the whole file, its
    last ``skip_footer`` non-blank lines are left out of it. A negative
    ``skip_footer`` raises ``ValueError``.

    ``max_field_size`` raises Python's ``csv`` field size limit (131,072
    characters by default) while the file is read. The limit is process-wide
    in the ``csv`` module, so the previous value is restored when the stream
    closes, also after an error.
    """
    if skip_lines < 0:
        raise ValueError(f"skip_lines must be >= 0, got {skip_lines}")
    if skip_footer < 0:
        raise ValueError(f"skip_footer must be >= 0, got {skip_footer}")
    name = display_name(path)  # as given: Path() would change the separators on Windows
    path = Path(path)  # the rest of the reader works on Path objects
    previous_limit = None if max_field_size is None else csv.field_size_limit(max_field_size)
    try:
        with _open_rows(
            path, name, max_rows, delimiter, encoding, skip_lines, skip_footer
        ) as stream:
            yield stream
    finally:
        if previous_limit is not None:
            csv.field_size_limit(previous_limit)


@contextmanager
def _open_rows(
    path: Path,
    name: str,
    max_rows: int | None,
    delimiter: str,
    encoding: str,
    skip_lines: int = 0,
    skip_footer: int = 0,
) -> Iterator[RowStream]:
    """``open_rows`` without the field size handling; ``name`` is used in messages."""
    with _text_stream(path, name, encoding) as (handle, compressed):
        try:
            first = handle.readline()
            declared = declared_delimiter(first)
            if declared is not None:
                first = ""  # a declaration, not data
                if delimiter == DELIMITER_AUTO:
                    delimiter = declared
                elif delimiter != declared:
                    raise DelimiterDetectionError(
                        f"'{name}' declares the {_describe(declared)} delimiter "
                        f"in its first line (sep={declared}), but the delimiter in use is "
                        f"{_describe(delimiter)}; pass --delimiter auto to follow the file"
                    )
            if skip_lines:
                first = _skip(handle, name, first, skip_lines)
            detected = delimiter == DELIMITER_AUTO
            sample = first
            whole = False  # the sample holds the whole file
            if detected and len(first) <= SNIFF_CHARS:
                sample += handle.read(SNIFF_CHARS + 1 - len(first))
                if len(sample) > SNIFF_CHARS:
                    sample += handle.readline()  # end the sample on a line boundary
                else:
                    whole = True
        except UnicodeDecodeError as exc:
            raise _encoding_error(path, name, compressed, encoding) from exc
        except UnicodeError as exc:
            raise _other_unicode_error(name, encoding, exc) from exc
        except _STREAM_ERRORS as exc:
            raise _read_error(name, exc) from exc
        if detected:
            judged = sample
            if whole and skip_footer:
                judged = _without_last_lines(sample, skip_footer)  # the footer is not data
            try:
                delimiter = detect_delimiter(judged)
            except DelimiterDetectionError as exc:
                hinted = _detection_hint(exc, sample, whole, skip_lines, skip_footer)
                if hinted is exc:
                    raise
                raise hinted from exc
        # Parse what was read ahead again, then continue with the rest of the stream.
        lines = chain(io.StringIO(sample, newline=""), handle)

        # Fail closed on malformed quoted cells: permissive csv.reader silently
        # accepts unterminated quotes and stray text after a closing quote.
        reader = csv.reader(lines, delimiter=delimiter, strict=True)
        records = iter(reader)
        counter = _LineCounter(reader, (0 if declared is None else 1) + skip_lines)
        header = next(
            (r for r in _guarded(path, records, counter, compressed, encoding, name) if r), None
        )
        if header is None:
            if skip_lines:
                raise EmptyFileError(
                    f"'{name}' has no header row after the {skip_lines} lines "
                    "skipped by --skip-lines"
                )
            raise EmptyFileError(f"'{name}' is empty (no header row)")
        yield RowStream(
            path,
            name,
            records,
            counter,
            header,
            max_rows,
            delimiter,
            detected,
            compressed,
            encoding,
            sep_line=declared is not None,
            skipped_lines=skip_lines,
            skipped_footer=skip_footer,
        )


def _detection_hint(
    exc: DelimiterDetectionError, sample: str, whole: bool, skip_lines: int, skip_footer: int
) -> DelimiterDetectionError:
    """``exc`` with a ``--skip-lines`` or ``--skip-footer`` suggestion when one fits.

    Title lines are looked for first (#161), then, when ``sample`` holds the
    whole file, a footer (#192). Neither is looked for once its option is given.
    """
    titles = None if skip_lines else title_lines(sample)
    if titles is not None:
        return DelimiterDetectionError(
            f"{exc.message}; if the file starts with {titles} title "
            f"{'line' if titles == 1 else 'lines'} before the header, "
            f"skip {'it' if titles == 1 else 'them'} with --skip-lines {titles}"
        )
    footer = footer_lines(sample) if whole and not skip_footer else None
    if footer is not None:
        return DelimiterDetectionError(
            f"{exc.message}; if the file ends with {footer} footer "
            f"{'line' if footer == 1 else 'lines'} after the data, "
            f"skip {'it' if footer == 1 else 'them'} with --skip-footer {footer} "
            f"(add one for each totals row above {'it' if footer == 1 else 'them'})"
        )
    return exc


def _skip(handle: io.TextIOWrapper, name: str, first: str, count: int) -> str:
    """Skip ``count`` lines of ``handle``, ``first`` (already read, or ``""``) being the first.

    Returns the line after them, the first one the CSV reader sees. Raises
    ``EmptyFileError`` when the file ends before that line.
    """
    line = first or handle.readline()
    for _ in range(count):
        if not line:
            break
        line = handle.readline()
    if not line:
        raise EmptyFileError(
            f"'{name}' has no header row: it ends within the {count} lines skipped by --skip-lines"
        )
    return line


def read_table(
    path: PathArg,
    max_rows: int | None = None,
    delimiter: str = ",",
    encoding: str = DEFAULT_ENCODING,
    max_field_size: int | None = None,
    skip_lines: int = 0,
    skip_footer: int = 0,
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
        skip_lines=skip_lines,
        skip_footer=skip_footer,
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
            skipped_lines=stream.skipped_lines,
            skipped_footer=stream.skipped_footer,
        )
