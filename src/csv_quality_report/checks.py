"""Optional quality gates evaluated on a finished ``Report``.

Thresholds turn the report into a pass/fail signal for pipelines: the CLI
still prints the full report, lists failed checks on stderr and exits with
``EXIT_CHECKS`` when at least one check fails.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .compare import Comparison
from .inference import parse_datetime
from .profile import ColumnProfile, Report

CHECK_MAX_MISSING = "max_missing"
CHECK_MAX_DUPLICATES = "max_duplicates"
CHECK_REQUIRED_COLUMN = "required_column"
CHECK_COLUMN_TYPE = "column_type"
CHECK_MAX_AFFIXES = "max_affixes"
CHECK_VALUE_RANGE = "value_range"
CHECK_SCHEMA_CHANGE = "schema_change"
# A bound of a --range check: a number for int/float columns, a date for date
# and datetime columns, a datetime for date and datetime columns, None for an
# open side.
Bound = int | float | date | datetime | None
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
        if self.check == CHECK_SCHEMA_CHANGE:
            if self.passed:
                return "no columns added, removed or retyped since the baseline"
            noun = "change" if self.value == 1 else "changes"
            return f"{int(self.value)} schema {noun} since the baseline: {self.detail}"
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
        if self.detail:  # values of the right type that cannot be compared with the bounds
            return f"column '{self.column}' cannot be checked against {span} ({self.detail})"
        verb = "is within" if self.passed else "has values outside"
        first, last = (_exact(v) for v in self.observed)
        return f"column '{self.column}' {verb} {span} (min {first}, max {last})"


# Column types a range applies to, by the kind of its bounds. Dates and
# date-times apply to both temporal types; see docs/decisions/0003.
_RANGE_TYPES = {
    "int or float": {"int", "float"},
    "date": {"date", "datetime"},
    "datetime": {"date", "datetime"},
}


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


def schema_change_check(comparison: Comparison) -> CheckResult:
    """A check that fails when columns were added, removed or changed type since the baseline."""
    parts = []
    if comparison.added_columns:
        parts.append("added " + ", ".join(f"'{name}'" for name in comparison.added_columns))
    if comparison.removed_columns:
        parts.append("removed " + ", ".join(f"'{name}'" for name in comparison.removed_columns))
    parts.extend(
        f"'{change.column}' {change.before} -> {change.after}" for change in comparison.type_changes
    )
    return CheckResult(
        check=CHECK_SCHEMA_CHANGE,
        column=None,
        limit=0,
        value=comparison.schema_changes,
        passed=comparison.schema_changes == 0,
        detail="; ".join(parts),
    )


def _bound_kind(bound: Bound) -> str:
    """``number``, ``date`` or ``date-time`` (``datetime`` is a subclass of ``date``)."""
    if isinstance(bound, datetime):
        return "date-time"
    return "date" if isinstance(bound, date) else "number"


def range_bounds_problem(low: Bound, high: Bound) -> str | None:
    """Why ``low`` and ``high`` cannot bound one range, or ``None`` when they can.

    Both bounds must be of the same kind (numbers, dates or date-times), and
    two date-times must both have a UTC offset or both lack one, since the two
    cannot be ordered. An open side (``None``) goes with any bound.
    """
    if low is None or high is None:
        return None
    if _bound_kind(low) != _bound_kind(high):
        return "both bounds must be numbers, both dates or both date-times"
    if isinstance(low, datetime) and isinstance(high, datetime):
        if (low.tzinfo is None) != (high.tzinfo is None):
            return "both date-times must have a UTC offset, or neither"
    return None


def _within(first: Any, last: Any, low: Any, high: Any) -> bool:
    """True when ``first..last`` lies inside the inclusive bounds (``None`` is open)."""
    return (low is None or first >= low) and (high is None or last <= high)


def _range_check(name: str, column: ColumnProfile, bounds: ValueRange) -> CheckResult:
    """The ``value_range`` check of one column against inclusive ``bounds``.

    Dates and date-times are compared as described in ADR 0003: date bounds
    compare calendar days, date-time bounds compare times (instants when the
    values have a UTC offset), and a comparison that would need a guessed time
    zone fails and says why.
    """
    low, high = bounds
    if isinstance(low, datetime) or isinstance(high, datetime):
        expected = "datetime"
    elif isinstance(low, date) or isinstance(high, date):
        expected = "date"
    else:
        expected = "int or float"
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
    if expected == "int or float":
        return result(_within(*seen, low, high), observed=seen)
    if column.min is None:  # a datetime column mixing values with and without an offset
        return result(False, "it mixes values with and without a UTC offset, so it has no range")
    # Date and datetime columns report ISO 8601 text that parse_datetime accepts.
    first, last = (_moment(value) for value in seen)
    with_offset = first.tzinfo is not None
    if expected == "date":
        if with_offset:
            return result(
                False,
                "its values have a UTC offset, so their calendar day depends on the time zone; "
                "use date-times with an offset as bounds",
            )
        return result(_within(first.date(), last.date(), low, high), observed=seen)
    bound = low if low is not None else high  # both have an offset, or neither
    if with_offset != (isinstance(bound, datetime) and bound.tzinfo is not None):
        detail = (
            "its values have a UTC offset and the bounds do not"
            if with_offset
            else "its values have no UTC offset and the bounds do"
        )
        return result(False, detail)
    return result(_within(first, last, low, high), observed=seen)


def _moment(value: int | float | str | None) -> datetime:
    """The date-time of a date or datetime column's min or max (a date is midnight)."""
    moment = parse_datetime(str(value))
    assert moment is not None, value  # the column type guarantees it
    return moment


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
    columns, ``datetime.date`` values for ``date`` and ``datetime`` columns
    (comparing calendar days), or ``datetime.datetime`` values for ``date``
    and ``datetime`` columns (comparing times; instants when the values have
    a UTC offset). The column's min and max must lie within them; a column
    with no values passes. A column of another type fails and says so (naming
    the stray values when its type hint fits), and so does a comparison that
    would need a guessed time zone (see ADR 0003). Bounds of different kinds,
    or date-times with and without an offset, raise ``ValueError``. Unknown
    names fail as ``required_column``.

    ``required_columns`` are matched exactly (case-sensitive) against the
    file's whole header (``Report.header``, after duplicate-name suffixes),
    also when only some columns were profiled; each one gives a check with
    ``value`` 1 when present and 0 when missing (``limit`` is 1). A
    per-column check on a column that exists but was not profiled raises
    ``ValueError``.

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
    # Required columns are looked up in the whole header, also when only some
    # columns were profiled (``Report.selected_columns``).
    header = list(report.header) or [col.name for col in report.columns]
    present = set(header)
    listed = ", ".join(header[:_MAX_LISTED]) + (", ..." if len(header) > _MAX_LISTED else "")
    by_name = {col.name: col for col in report.columns}
    gated = [*(column_max_missing or {}), *(column_types or {}), *(column_max_affixes or {})]
    unprofiled = [name for name in [*gated, *(column_ranges or {})] if name in present]
    unprofiled = [name for name in unprofiled if name not in by_name]
    if unprofiled:
        raise ValueError(
            f"column '{unprofiled[0]}' has a per-column check but was not selected for profiling"
        )
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
        problem = range_bounds_problem(*bounds)
        if problem:
            raise ValueError(f"invalid range for column {name!r}: {problem}")
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
