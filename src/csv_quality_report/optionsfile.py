"""Read command-line options from a text file (``--options-file``, #323).

A pipeline that checks a scheduled export needs a long command line: the
reading options of the export plus a dozen quality gates. Kept in a file, the
same checks can be versioned and shared between a local run, a cron job and
CI, and column names with spaces (``Fecha entrega``) can be quoted, which the
GitHub Action's whitespace-split ``args`` cannot do.

The format is deliberately small (see ``docs/decisions/0010-options-file.md``):

- one or more options per line, separated by spaces or tabs;
- single or double quotes group words (``--unique "Nro de guía"``), and a
  quoted part joins the text next to it (``--na="s/d,sin dato"``);
- a line whose first non-blank character is ``#`` is a comment; there are no
  inline comments, so ``--na #N/A`` is the token ``#N/A``;
- backslashes are literal, so Windows paths and regular expressions
  (``--pattern 'CUIT=\\d{2}-\\d{8}-\\d'``) need no escaping;
- UTF-8, with or without a BOM; ``\\r\\n`` line endings are accepted.

Every problem is a :class:`OptionsFileError` (a ``ValueError``) whose message
names the file and, when it has one, the line.
"""

from __future__ import annotations

from collections.abc import Callable

#: Larger files are refused: an options file holds a few lines of options,
#: so a bigger one is most likely a CSV passed by mistake.
MAX_OPTIONS_FILE_BYTES = 1024 * 1024

_BOM = b"\xef\xbb\xbf"
_SEPARATORS = " \t"
_QUOTES = "\"'"


class OptionsFileError(ValueError):
    """An options file that cannot be read or parsed."""


def _is_control(char: str) -> bool:
    """C0 controls (except tab), DEL and C1 controls, as the Action refuses them."""
    code = ord(char)
    return (code < 32 and char != "\t") or 127 <= code <= 159


def split_options_line(line: str) -> list[str]:
    """The tokens of one line of an options file.

    Spaces and tabs outside quotes separate tokens; single or double quotes
    group words and are removed, and an empty pair of quotes is an empty
    token. Raises ``ValueError`` for a quote that is not closed on the line.

    >>> split_options_line('--require-when "Fecha entrega" Estado=Entregado')
    ['--require-when', 'Fecha entrega', 'Estado=Entregado']
    """
    tokens: list[str] = []
    current: list[str] = []
    started = False
    quote = ""
    for char in line:
        if quote:
            if char == quote:
                quote = ""
            else:
                current.append(char)
        elif char in _QUOTES:
            quote = char
            started = True
        elif char in _SEPARATORS:
            if started:
                tokens.append("".join(current))
                current = []
                started = False
        else:
            current.append(char)
            started = True
    if quote:
        raise ValueError(f"unclosed {quote} quote")
    if started:
        tokens.append("".join(current))
    return tokens


def parse_options_text(text: str) -> list[tuple[int, str]]:
    """The tokens of an options file's text, each with its 1-based line number.

    Raises ``ValueError`` (with the line in the message) for control
    characters and unclosed quotes.
    """
    tokens: list[tuple[int, str]] = []
    for number, line in enumerate(text.split("\n"), start=1):
        line = line.removesuffix("\r")
        bad = next((char for char in line if _is_control(char)), None)
        if bad is not None:
            raise ValueError(
                f"line {number}: control character U+{ord(bad):04X} "
                "(only spaces and tabs separate options)"
            )
        if line.lstrip(_SEPARATORS).startswith("#"):
            continue
        try:
            tokens.extend((number, token) for token in split_options_line(line))
        except ValueError as exc:
            raise ValueError(f"line {number}: {exc}") from None
    return tokens


def read_options_bytes(path: str) -> bytes:
    """The raw content of the options file at ``path`` (at most 1 MiB).

    Raises :class:`OptionsFileError` for ``-`` (standard input is the CSV),
    a file that cannot be read and a file over :data:`MAX_OPTIONS_FILE_BYTES`.
    """
    where = f"--options-file '{path}'"
    if path == "-":
        raise OptionsFileError(
            f"{where}: standard input is reserved for the CSV; write the options to a file"
        )
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_OPTIONS_FILE_BYTES + 1)
    except OSError as exc:
        raise OptionsFileError(f"{where}: cannot read it: {exc.strerror or exc}") from None
    if len(data) > MAX_OPTIONS_FILE_BYTES:
        raise OptionsFileError(
            f"{where}: larger than 1 MiB; an options file holds command-line options "
            "(was a CSV file passed by mistake?)"
        )
    return data


def parse_options_bytes(
    data: bytes, path: str, *, is_options_file: Callable[[str], bool]
) -> list[tuple[int, str]]:
    """The tokens of an options file's content, each with its 1-based line number.

    ``path`` only names the file in messages. ``is_options_file`` tells
    whether a token is ``--options-file`` (or one of its abbreviations):
    files cannot include other files. A bare ``--`` is refused too, since it
    would end the options of the whole command line. Raises
    :class:`OptionsFileError`.
    """
    where = f"--options-file '{path}'"
    data = data.removeprefix(_BOM)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = data.count(b"\n", 0, exc.start) + 1
        raise OptionsFileError(
            f"{where}: line {line}: not valid UTF-8 (byte 0x{data[exc.start]:02X}); "
            "save the file as UTF-8"
        ) from None
    try:
        tokens = parse_options_text(text)
    except ValueError as exc:
        raise OptionsFileError(f"{where}: {exc}") from None
    for line, token in tokens:
        if token == "--":
            raise OptionsFileError(
                f"{where}: line {line}: a bare -- cannot be used in an options file"
            )
        if is_options_file(token):
            raise OptionsFileError(
                f"{where}: line {line}: an options file cannot include another one "
                f"({token.partition('=')[0]})"
            )
    return tokens


def read_options_file(path: str, *, is_options_file: Callable[[str], bool]) -> list[str]:
    """The options in the file at ``path``, in order.

    :func:`read_options_bytes` then :func:`parse_options_bytes`, without the
    line numbers. Raises :class:`OptionsFileError`.
    """
    data = read_options_bytes(path)
    return [token for _, token in parse_options_bytes(data, path, is_options_file=is_options_file)]
