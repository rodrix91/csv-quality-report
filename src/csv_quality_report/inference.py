"""Heuristic column type inference."""

from __future__ import annotations

import re
from datetime import date
from typing import Iterable

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
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


def infer_type(values: Iterable[str]) -> str:
    """Infer one type for already-stripped, non-missing ``values``.

    Order: bool (true/false, any case), int, float, date (YYYY-MM-DD),
    otherwise string. A column with no values is reported as ``string``.
    """
    items = list(values)
    if not items:
        return TYPE_STRING
    if all(v.lower() in _BOOLS for v in items):
        return TYPE_BOOL
    if all(_INT_RE.match(v) for v in items):
        return TYPE_INT
    if all(_FLOAT_RE.match(v) for v in items):
        return TYPE_FLOAT
    if all(_is_date(v) for v in items):
        return TYPE_DATE
    return TYPE_STRING
