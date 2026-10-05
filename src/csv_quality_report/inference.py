"""Heuristic column type inference."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import date

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_FLOAT_COMMA_RE = re.compile(r"^[+-]?(\d+,\d*|,\d+|\d+)([eE][+-]?\d+)?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BOOLS = frozenset({"true", "false"})

TYPE_BOOL = "bool"
TYPE_INT = "int"
TYPE_FLOAT = "float"
TYPE_DATE = "date"
TYPE_STRING = "string"


def _is_date(value: str) -> bool:
    if not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


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
    otherwise string. A column with no values is reported as ``string``.
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
    return TYPE_STRING
