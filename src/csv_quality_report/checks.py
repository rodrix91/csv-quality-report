"""Optional quality gates evaluated on a finished ``Report``.

Thresholds turn the report into a pass/fail signal for pipelines: the CLI
still prints the full report, lists failed checks on stderr and exits with
``EXIT_CHECKS`` when at least one check fails.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from .profile import ColumnProfile, Report

CHECK_MAX_MISSING = "max_missing"
CHECK_MAX_DUPLICATES = "max_duplicates"
CHECK_REQUIRED_COLUMN = "required_column"
CHECK_COLUMN_TYPE = "column_type"
CHECK_MAX_AFFIXES = "max_affixes"
CHECK_VALUE_RANGE = "value_range"
# A bound of a --range check: a number for int/float columns, a date for date
# columns, None for an open side.
Bound = int | float | date | None
ValueRange = tuple[Bound, Bound]
Observed = tuple[int | float | str | None, int | float | str | None]  # column min, max
COLUMN_TYPES = ("int", "float", "bool", "date", "datetime", "string")
# Inferred column types that satisfy each required type.
_SATISFIES = {
    "int": {"int"},
    "float": {"int", "float"},
    "bool": {"bool"},
    "date": {"date"},
    "datetime": {"date", "datetime"},
    "string": set(COLUMN_TYPES),
}
_MAX_LISTED = 10  # columns named in a "missing column" message


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one threshold on one column (or on the whole file)."""

    check: str
    column: str | None  # None for file-level checks
    limit: float
    value: float
    passed: bool
    detail: str = ""  # extra context for messages (not part of the JSON output)
    hint: str = ""  # a present column that matches after stripping whitespace
    expected: str = ""  # column_type checks: the required type
    actual: str = ""  # column_type checks: the inferred type
    found: tuple[tuple[str, int], ...] = ()  # max_affixes checks: (affix, cells)
    bounds: ValueRange = (None, None)  # value_range checks: the allowed range
    observed: Observed = (None, None)  # value_range checks: the column's min and max

    def describe(self) -> str:
        """One-line, human-readable explanation used on stderr and in Markdown."""
        if self.check == CHECK_MAX_MISSING:
            return (
                f"column '{self.column}' has {_fmt(self.value)}% missing values "
                f"(limit {_fmt(self.limit)}%)"
            )
        if self.check == CHECK_REQUIRED_COLUMN:
            if self.passed:
                return f"required column '{self.column}' is present"
            message = f"required column '{self.column}' is missing (columns: {self.detail})"
            return message + (f"; did you mean '{self.hint}'?" if self.hint else "")
        if self.check == CHECK_COLUMN_TYPE:
            if self.passed:
                return f"column '{self.column}' is {self.actual}, as required ({self.expected})"
            message = f"column '{self.column}' is {self.actual}, expected {self.expected}"
            return message + (f" ({self.detail})" if self.detail else "")
        if self.check == CHECK_MAX_AFFIXES:
            count = int(self.value)
            noun = "number affix" if count == 1 else "number affixes"
            verb = "mixes" if count > 1 else "has"
            found = ", ".join(f'"{a}" in {n} cell' + ("s" if n != 1 else "") for a, n in self.found)
            return f"column '{self.column}' {verb} {count} {noun}" + (
                f": {found} (limit {int(self.limit)})" if found else f" (limit {int(self.limit)})"
            )
        if self.check == CHECK_VALUE_RANGE:
            return self._describe_range()
        return f"{_fmt(self.value)} duplicate rows (limit {_fmt(self.limit)})"

    def _describe_range(self) -> str:
        # Open sides stay empty, as in the option: 0.., ..5000, 0..5000.
        span = "..".join("" if bound is None else _exact(bound) for bound in self.bounds)
        if self.actual not in _RANGE_TYPES[self.expected]:
            if self.passed:
                return f"column '{self.column}' has no values to check against {span}"
            message = (
                f"column '{self.column}' is {self.actual}, a range needs {self.expected} values"
            )
            return message + (f" ({self.detail})" if self.detail else "")
        verb = "is within" if self.passed else "has values outside"
        first, last = (_exact(v) for v in self.observed)
        return f"column '{self.column}' {verb} {span} (min {first}, max {last})"


# Column types a range applies to, by the kind of its bounds.
_RANGE_TYPES = {"int or float": {"int", "float"}, "date": {"date"}}


def _exact(value: int | float | str | date | None) -> str:
    """A bound or an observed value as written: 80000.0 as 80000, 1234.56 as 1234.56."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e16:
        return str(int(value))
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _fmt(number: float) -> str:
    """Print 10.0 as 10 and keep real decimals (12.5, 33.3333)."""
    return f"{number:g}" if number == int(number) else f"{number:.4g}"


def _within(first: Any, last: Any, low: Any, high: Any) -> bool:
    """True when ``first..last`` lies inside the inclusive bounds (``None`` is open)."""
    return (low is None or first >= low) and (high is None or last <= high)


def _range_check(name: str, column: ColumnProfile, bounds: ValueRange) -> CheckResult:
    """The ``value_range`` check of one column against inclusive ``bounds``."""
    low, high = bounds
    expected = "date" if isinstance(low, date) or isinstance(high, date) else "int or float"
    wanted = _RANGE_TYPES[expected]

    def result(passed: bool, detail: str = "", observed: Observed = (None, None)) -> CheckResult:
        return CheckResult(
            check=CHECK_VALUE_RANGE,
            column=name,
            limit=1,
            value=1 if passed else 0,
            passed=passed,
            detail=detail,
            expected=expected,
            actual=column.type,
            bounds=bounds,
            observed=observed,
        )

    if column.distinct == 0:
        return result(True)
    if column.type not in wanted:
        hint = column.type_hint
        if hint is None or hint.type not in wanted:
            return result(False)
        noun = "value does" if hint.nonconforming == 1 else "values do"
        examples = ", ".join(f'"{v}"' for v in hint.examples)
        return result(False, f"{hint.nonconforming} {noun} not fit: {examples}")
    seen = (column.min, column.max)
    if expected == "date":  # date columns report ISO 8601 text
        first, last = (date.fromisoformat(str(v)) for v in seen)
        return result(_within(first, last, low, high), observed=seen)
    return result(_within(*seen, low, high), observed=seen)


def evaluate(
    report: Report,
    max_missing: float | None = None,
    max_duplicates: int | None = None,
    required_columns: Iterable[str] = (),
    column_max_missing: Mapping[str, float] | None = None,
    column_types: Mapping[str, str] | None = None,
    column_max_affixes: Mapping[str, int] | None = None,
    column_ranges: Mapping[str, ValueRange] | None = None,
) -> list[CheckResult]:
    """Evaluate the requested thresholds; a value equal to its limit passes.

    ``column_max_missing`` maps column names to their own missing-value
    limit, which overrides ``max_missing`` for that column and can be used
    without it. A limit for a column that is not in the header fails as a
    ``required_column`` check, because it usually means a typo or a renamed
    column; it is not silently ignored.

    ``column_types`` maps column names to a required type from
    ``COLUMN_TYPES``. A column satisfies it when its inferred type can be used
    as that type (int columns satisfy float, date columns satisfy datetime,
    every column satisfies string); a column with no values passes. When a
    failing string column has a type hint matching the requirement, the
    message names the stray values. Unknown names fail as ``required_column``.

    ``column_max_affixes`` maps column names to the most distinct number
    affixes (``Report.number_affixes``) the column may contain; ``1`` fails a
    column that mixes currencies or units. The report must have been built
    with number affixes, or no affix could ever be found: ``ValueError`` is
    raised instead of passing silently. Unknown names fail as
    ``required_column``.

    ``column_ranges`` maps column names to ``(min, max)`` bounds, inclusive,
    either of which may be ``None``: numbers for ``int`` and ``float``
    columns, ``datetime.date`` values for ``date`` columns. The column's min
    and max must lie within them; a column with no values passes. A column of
    another type fails and says so (naming the stray values when its type
    hint fits). Unknown names fail as ``required_column``.

    ``required_columns`` are matched exactly (case-sensitive) against the
    reported header, after duplicate-name suffixes; each one gives a check
    with ``value`` 1 when present and 0 when missing (``limit`` is 1).

    The missing percentage is computed exactly from the counts, not from the
    one-decimal ``missing_pct`` shown in the report, so rounding can never
    hide a value just above the limit.
    """
    results: list[CheckResult] = []
    column_limits = dict(column_max_missing or {})
    for col in report.columns:
        limit = column_limits.get(col.name, max_missing)
        if limit is None:
            continue
        pct = 100.0 * col.missing / report.rows if report.rows else 0.0
        results.append(
            CheckResult(
                check=CHECK_MAX_MISSING,
                column=col.name,
                limit=limit,
                value=round(pct, 4),
                passed=pct <= limit,
            )
        )
    if max_duplicates is not None:
        results.append(
            CheckResult(
                check=CHECK_MAX_DUPLICATES,
                column=None,
                limit=max_duplicates,
                value=report.duplicate_rows,
                passed=report.duplicate_rows <= max_duplicates,
            )
        )
    header = [col.name for col in report.columns]
    present = set(header)
    listed = ", ".join(header[:_MAX_LISTED]) + (", ..." if len(header) > _MAX_LISTED else "")
    by_name = {col.name: col for col in report.columns}
    required_types = dict(column_types or {})
    for name, expected in required_types.items():
        column = by_name.get(name)
        if column is None:
            continue  # reported below as a missing required column
        ok = column.distinct == 0 or column.type in _SATISFIES[expected]
        detail = ""
        hint = column.type_hint
        if not ok and hint is not None and hint.type in _SATISFIES[expected]:
            noun = "value does" if hint.nonconforming == 1 else "values do"
            examples = ", ".join(f'"{v}"' for v in hint.examples)
            detail = f"{hint.nonconforming} {noun} not fit: {examples}"
        results.append(
            CheckResult(
                check=CHECK_COLUMN_TYPE,
                column=name,
                limit=1,
                value=1 if ok else 0,
                passed=ok,
                detail=detail,
                expected=expected,
                actual=column.type,
            )
        )
    affix_limits = dict(column_max_affixes or {})
    if affix_limits and not report.number_affixes:
        raise ValueError("max_affixes checks need a report built with number affixes")
    for name, max_affixes in affix_limits.items():
        column = by_name.get(name)
        if column is None:
            continue  # reported below as a missing required column
        results.append(
            CheckResult(
                check=CHECK_MAX_AFFIXES,
                column=name,
                limit=max_affixes,
                value=len(column.affixes),
                passed=len(column.affixes) <= max_affixes,
                found=column.affixes,
            )
        )
    ranges = dict(column_ranges or {})
    for name, bounds in ranges.items():
        column = by_name.get(name)
        if column is None:
            continue  # reported below as a missing required column
        results.append(_range_check(name, column, bounds))
    unknown_limited = (
        name
        for name in [*column_limits, *required_types, *affix_limits, *ranges]
        if name not in present
    )
    for name in dict.fromkeys([*required_columns, *unknown_limited]):
        found = name in present
        near = [] if found else [h for h in header if h.strip() == name.strip()]
        results.append(
            CheckResult(
                check=CHECK_REQUIRED_COLUMN,
                column=name,
                limit=1,
                value=1 if found else 0,
                passed=found,
                detail="" if found else listed,
                hint=near[0] if near else "",
            )
        )
    return results
