"""Heuristic column type inference."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import date, datetime

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
