"""Heuristic column type inference."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import date, datetime
from functools import lru_cache

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_FLOAT_COMMA_RE = re.compile(r"^[+-]?(\d+,\d*|,\d+|\d+)([eE][+-]?\d+)?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# ISO 8601 extended date + time: seconds and up to 6 fraction digits optional,
# then an optional UTC designator or offset (+HH:MM, +HHMM, +HH).
_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}(:?\d{2})?)?$"
)
_BOOLS = frozenset({"true", "false"})
# Python refuses int() on strings with more digits than its limit (4300 by
# default, configurable). Shorter strings matching _INT_RE always convert, so
# the conversion is only attempted near the limit (640 is the lowest value the
# limit can be set to, other than 0 for "no limit").
_SAFE_INT_DIGITS = 640
# Every int, float, date or datetime value starts with one of these: digits,
# signs, or "." / "," (".5", ",5"). Booleans are the only typed values that
# start with a letter (t or f, in any case).
_TYPED_FIRST_CHARS = frozenset("0123456789+-.,")
_BOOL_FIRST_CHARS = frozenset("tTfF")


# Characters that can appear in an int, float, date or datetime value. A value
# with any other character is a string, which one linear regex search finds
# without the backtracking a union of the exact patterns would cost.
_NOT_NUMERIC_OR_TEMPORAL_RE = re.compile(r"[^0-9+\-.,eE:TZ ]")

TYPE_BOOL = "bool"
TYPE_INT = "int"
TYPE_FLOAT = "float"
TYPE_DATE = "date"
TYPE_DATETIME = "datetime"
TYPE_STRING = "string"


def _is_date(value: str) -> bool:
    if not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def parse_datetime(value: str) -> datetime | None:
    """Parse a strict ISO 8601 date-time (or a plain date, as midnight); else ``None``.

    The regex keeps the accepted forms identical on every supported Python
    version: ``datetime.fromisoformat`` itself also takes compact or partial
    forms (``20261005T1430``, ``2026-10-05T14``) that are not accepted here.
    """
    if not (_DATETIME_RE.match(value) or _DATE_RE.match(value)):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:  # impossible calendar values, hour 24, offset >= 24h
        return None


def _is_int(value: str) -> bool:
    if not _INT_RE.match(value):
        return False
    if len(value) < _SAFE_INT_DIGITS:  # far below Python's digit limit: always converts
        return True
    try:
        int(value)
    except ValueError:  # e.g. more digits than Python's int/str conversion limit
        return False
    return True


def parse_float(value: str, decimal_comma: bool = False) -> float:
    """Convert an already-validated float literal to ``float``.

    With ``decimal_comma`` the literal uses ``,`` as its decimal mark (``10,5``).
    """
    return float(value.replace(",", ".")) if decimal_comma else float(value)


def _is_float(value: str, decimal_comma: bool = False) -> bool:
    pattern = _FLOAT_COMMA_RE if decimal_comma else _FLOAT_RE
    # Reject values that overflow to inf (e.g. "1e999"): they are not usable numbers.
    return bool(pattern.match(value)) and math.isfinite(parse_float(value, decimal_comma))


def infer_type(values: Iterable[str], decimal_comma: bool = False) -> str:
    """Infer one type for already-stripped, non-missing ``values``.

    Order: bool (true/false, any case), int, float, date (YYYY-MM-DD),
    datetime (ISO 8601 date and time; plain dates may be mixed in), otherwise
    string. A column with no values is reported as ``string``.
    Numbers that cannot be represented (integers beyond Python's digit limit,
    floats that overflow to infinity such as ``1e999``) make the column ``string``.

    With ``decimal_comma`` floats must use ``,`` as the decimal mark (``10,5``)
    and values written with ``.`` are no longer floats. Thousands separators
    are never recognized.
    """
    items = list(values)
    if not items:
        return TYPE_STRING
    if all(v.lower() in _BOOLS for v in items):
        return TYPE_BOOL
    if all(_is_int(v) for v in items):
        return TYPE_INT
    if all(_is_float(v, decimal_comma) for v in items):
        return TYPE_FLOAT
    if all(_is_date(v) for v in items):
        return TYPE_DATE
    if all(parse_datetime(v) is not None for v in items):
        return TYPE_DATETIME
    return TYPE_STRING


def value_type(value: str, decimal_comma: bool = False) -> str:
    """Narrowest type of one stripped, non-missing value, by the ``infer_type`` rules.

    Equivalent to ``infer_type([value])`` but cheaper, because it is called
    once per distinct value. Two cheap filters (the first character, then one
    linear search for characters no typed value can contain) reject most
    text before the exact checks run. The order of the exact checks does not
    change the result: an int is also a float and is checked first, a date is
    checked before datetime, and the other types exclude each other.
    """
    first = value[:1]
    if first in _BOOL_FIRST_CHARS:  # only true/false start with a letter
        return TYPE_BOOL if value.lower() in _BOOLS else TYPE_STRING
    if first not in _TYPED_FIRST_CHARS or _NOT_NUMERIC_OR_TEMPORAL_RE.search(value):
        return TYPE_STRING  # most text is rejected by these two cheap checks
    if _is_int(value):
        return TYPE_INT
    if _is_float(value, decimal_comma):
        return TYPE_FLOAT
    if _is_date(value):
        return TYPE_DATE
    if parse_datetime(value) is not None:
        return TYPE_DATETIME
    return TYPE_STRING


# Thousands separators: the option value and the characters it accepts. "space"
# also accepts the no-break spaces that spreadsheets insert (U+00A0, U+202F).
THOUSANDS_SEPARATORS = {".": ".", ",": ",", " ": " \u00a0\u202f"}


@lru_cache(maxsize=8)
def _grouped_number(
    thousands: str, decimal_comma: bool
) -> tuple[re.Pattern[str], dict[int, int | None]]:
    """Regex for a number with thousands groups, and a table that removes them."""
    chars = THOUSANDS_SEPARATORS[thousands]
    sep = "[" + "".join(re.escape(c) for c in chars) + "]"
    mark = "," if decimal_comma else r"\."
    pattern = re.compile(rf"^[+-]?\d{{1,3}}(?:{sep}\d{{3}})+(?:{mark}\d*)?$")
    return pattern, str.maketrans("", "", chars)


def strip_thousands(value: str, thousands: str, decimal_comma: bool = False) -> str:
    """Remove the thousands separators of a correctly grouped number.

    ``1.234.567,5`` becomes ``1234567,5`` with ``thousands="."`` and a decimal
    comma. Groups must have exactly three digits after a first group of one to
    three, so ``1.23`` or ``12.34.56`` are left unchanged (and stay text if
    they are not numbers otherwise). Any other value is returned as is.
    """
    pattern, table = _grouped_number(thousands, decimal_comma)
    return value.translate(table) if pattern.match(value) else value


# Date orders for --date-order: the regex that reads one (with an optional time)
# and the positions of year, month and day among its groups.
DATE_ORDERS = ("dmy", "mdy", "ymd")
# ASCII digits only: \d would also accept digits of other scripts.
# Optional 12-hour marker: AM/PM in any case, with optional dots and spaces
# (2:30 PM, 2:30pm, 2:30 p.m., and the Spanish "p. m." with no-break spaces).
_SPACE = "[ \u00a0\u202f]?"
_MERIDIEM = rf"(?:{_SPACE}([AaPp])(?:\.{_SPACE})?[Mm]\.?)?"
_TIME = r"(?:([ T])([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?" + _MERIDIEM + ")?$"
_SHORT_FIRST_RE = re.compile(r"^([0-9]{1,2})([/.-])([0-9]{1,2})\2([0-9]{4})" + _TIME)
_YEAR_FIRST_RE = re.compile(r"^([0-9]{4})([/.-])([0-9]{1,2})\2([0-9]{1,2})" + _TIME)
_DATE_LAYOUTS = {  # order: (regex, group of year, group of month, group of day)
    "dmy": (_SHORT_FIRST_RE, 4, 3, 1),
    "mdy": (_SHORT_FIRST_RE, 4, 1, 3),
    "ymd": (_YEAR_FIRST_RE, 1, 3, 4),
}


def normalize_date(value: str, order: str) -> str:
    """Rewrite a date written in ``order`` as ISO 8601; return other values unchanged.

    ``05/10/2026`` becomes ``2026-10-05`` with ``order="dmy"`` and
    ``2026-05-10`` with ``"mdy"``. Day and month take one or two digits, the
    year four; the separator is ``/``, ``-`` or ``.``, the same one twice. An
    optional time (``H:MM`` or ``HH:MM:SS``) after a space or ``T`` is kept,
    with the hour padded to two digits. A 12-hour time (``2:30 PM``,
    ``2:30 p. m.``) is rewritten on the 24-hour clock; its hour must be 1 to
    12, or the value is returned unchanged. The calendar is not checked here:
    ``31/02/2026`` becomes ``2026-02-31``, which inference then rejects.
    """
    regex, year, month, day = _DATE_LAYOUTS[order]
    match = regex.match(value)
    if match is None:
        return value
    g = match.groups()
    iso = f"{g[year - 1]}-{g[month - 1]:0>2}-{g[day - 1]:0>2}"
    if g[4] is None:
        return iso
    hour = g[5]
    if g[8] is not None:  # 12-hour clock: 12 AM is 00, 12 PM is 12
        if not 1 <= int(hour) <= 12:
            return value
        hour = str(int(hour) % 12 + (12 if g[8] in "Pp" else 0))
    seconds = "" if g[7] is None else ":" + g[7]
    return f"{iso}{g[4]}{hour:0>2}:{g[6]}{seconds}"


BoolWords = tuple[tuple[str, str], ...]  # (true word, false word) pairs, as given


def bool_word_map(pairs: BoolWords) -> dict[str, str]:
    """Map each word of ``pairs``, casefolded, to ``"true"`` or ``"false"``.

    ``true`` and ``false`` are always recognized and cannot change meaning.
    Raises ``ValueError`` for an empty word, a pair whose words are equal
    (ignoring case), a word given as true in one pair and false in another, or
    a word that is already a number or a date: with ``1,0`` a quantity column
    holding 0, 1 and 5 would turn into text, and 0/1 columns are reported as
    ``int`` anyway.
    """
    mapping = {"true": "true", "false": "false"}
    for pair in pairs:
        if len(pair) != 2 or not all(word.strip() for word in pair):
            raise ValueError(f"boolean words must be two non-empty words: {pair!r}")
        true_word, false_word = (word.strip().casefold() for word in pair)
        for word in (true_word, false_word):
            if {value_type(word), value_type(word, decimal_comma=True)} - {TYPE_STRING, TYPE_BOOL}:
                raise ValueError(f"{word!r} is a number or a date, not a boolean word")
        if true_word == false_word:
            raise ValueError(f"{pair[0]!r} and {pair[1]!r} are the same word (case is ignored)")
        for word, meaning in ((true_word, "true"), (false_word, "false")):
            if mapping.setdefault(word, meaning) != meaning:
                raise ValueError(f"{word!r} cannot mean both true and false")
    return mapping


def normalize_bool(value: str, mapping: dict[str, str]) -> str:
    """``"true"`` or ``"false"`` for a word in ``mapping`` (any case); else ``value``."""
    return mapping.get(value.casefold(), value)


def check_date_order(order: str | None) -> None:
    """Raise ``ValueError`` for a date order other than ``None`` or one of ``DATE_ORDERS``."""
    if order is not None and order not in _DATE_LAYOUTS:
        raise ValueError(f"unsupported date order: {order!r} (use one of {', '.join(DATE_ORDERS)})")


def check_thousands(thousands: str | None, decimal_comma: bool) -> None:
    """Raise ``ValueError`` when the thousands separator is also the decimal mark."""
    if thousands is None:
        return
    if thousands not in THOUSANDS_SEPARATORS:
        raise ValueError(f"unsupported thousands separator: {thousands!r}")
    if thousands == "." and not decimal_comma:
        raise ValueError("'.' as thousands separator needs a decimal comma (--decimal-comma)")
    if thousands == "," and decimal_comma:
        raise ValueError("',' cannot be the thousands separator with a decimal comma")
