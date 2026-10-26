"""Optional quality gates evaluated on a finished ``Report``.

Thresholds turn the report into a pass/fail signal for pipelines: the CLI
still prints the full report, lists failed checks on stderr and exits with
``EXIT_CHECKS`` when at least one check fails.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from typing import Any

from .clock import format_stamp, parse_stamp
from .compare import Comparison, TypeChange
from .inference import parse_datetime
from .profile import (
    ColumnProfile,
    DomainProfile,
    KeyProfile,
    PatternProfile,
    Report,
    allowed_list,
    compile_pattern,
    key_columns,
)

CHECK_MAX_MISSING = "max_missing"
CHECK_MAX_DUPLICATES = "max_duplicates"
CHECK_REQUIRED_COLUMN = "required_column"
CHECK_COLUMN_TYPE = "column_type"
CHECK_MAX_AFFIXES = "max_affixes"
CHECK_VALUE_RANGE = "value_range"
CHECK_SCHEMA_CHANGE = "schema_change"
CHECK_ROW_DROP = "row_drop"
CHECK_MISSING_INCREASE = "missing_increase"
CHECK_UNIQUE = "unique"
CHECK_UNIQUE_KEY = "unique_key"
CHECK_BASELINE_AGE = "baseline_age"
CHECK_MAX_AGE = "max_age"
CHECK_MIN_ROWS = "min_rows"
CHECK_ALLOWED_VALUES = "allowed_values"
CHECK_PATTERN = "pattern"
# A baseline stamped up to this many seconds after the clock counts as 0
# seconds old (clocks of two machines differ a little); later is an error.
CLOCK_SKEW_TOLERANCE = 300
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
_NO_BASELINE_COUNT = "the baseline has no 'missing' count for it"
# Why a column named by a per-column missing_increase limit cannot be compared.
_NOT_IN_BASELINE = "the baseline has no column of that name"
_NOT_IN_FILE = "the file no longer has it"
_IN_NEITHER = "neither the file nor the baseline has it"
_UNCOMPARABLE = (_NO_BASELINE_COUNT, _NOT_IN_BASELINE, _NOT_IN_FILE, _IN_NEITHER)


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
    repeated: tuple[tuple[str, int], ...] = ()  # unique checks: most repeated (value, cells)
    key: tuple[str, ...] = ()  # unique_key checks: the key's columns
    repeated_keys: tuple[tuple[tuple[str, ...], int], ...] = ()  # unique_key: (values, rows)
    skipped: int = 0  # unique_key checks: rows with a missing key cell, not checked
    # schema_change checks with --allow-type-change: the rules given and the
    # type changes they tolerated (not counted in ``value``).
    allowed_rules: tuple[TypeChangeRule, ...] = ()
    tolerated: tuple[TypeChange, ...] = ()
    # schema_change checks with --allow-added-column / --allow-removed-column:
    # the names given and the added or removed columns they tolerated.
    allowed_added: tuple[str, ...] = ()
    tolerated_added: tuple[str, ...] = ()
    allowed_removed: tuple[str, ...] = ()
    tolerated_removed: tuple[str, ...] = ()
    generated_at: str | None = None  # baseline_age checks: the baseline's stamp
    newest: str | None = None  # max_age checks: the column's newest value, as reported
    allowed: tuple[str, ...] = ()  # allowed_values checks: the values given
    unexpected: tuple[tuple[str, int], ...] = ()  # allowed_values: most frequent (value, cells)
    pattern: str = ""  # pattern checks: the regular expression given
    mismatched: tuple[tuple[str, int], ...] = ()  # pattern checks: most frequent (value, cells)

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
            return self._describe_schema_change()
        if self.check == CHECK_ROW_DROP:
            change = f"fell {_fmt(self.value)}%" if self.value > 0 else "did not fall"
            return (
                f"row count {change} since the baseline "
                f"({self.detail} rows; limit {_fmt(self.limit)}%)"
            )
        if self.check == CHECK_MISSING_INCREASE:
            return self._describe_missing_increase()
        if self.check == CHECK_UNIQUE:
            return self._describe_unique()
        if self.check == CHECK_UNIQUE_KEY:
            return self._describe_unique_key()
        if self.check == CHECK_BASELINE_AGE:
            return self.detail
        if self.check == CHECK_MAX_AGE:
            return self._describe_max_age()
        if self.check == CHECK_ALLOWED_VALUES:
            return self._describe_allowed_values()
        if self.check == CHECK_PATTERN:
            return self._describe_pattern()
        if self.check == CHECK_MIN_ROWS:
            rows = int(self.value)
            noun = "data row" if rows == 1 else "data rows"
            return f"the file has {rows} {noun} (at least {int(self.limit)} required)"
        return f"{_fmt(self.value)} duplicate rows (limit {_fmt(self.limit)})"

    def _describe_schema_change(self) -> str:
        allowed = ""
        tolerated = [
            *(f"added '{name}'" for name in self.tolerated_added),
            *(f"removed '{name}'" for name in self.tolerated_removed),
            *(_type_change(t) for t in self.tolerated),
        ]
        if tolerated:
            allowed = " (allowed: " + "; ".join(tolerated) + ")"
        if self.passed:
            if tolerated:
                return "no schema changes since the baseline" + allowed
            return "no columns added, removed or retyped since the baseline"
        noun = "change" if self.value == 1 else "changes"
        return f"{int(self.value)} schema {noun} since the baseline: {self.detail}" + allowed

    def _describe_unique(self) -> str:
        if self.passed:
            return f"column '{self.column}' has no repeated values"
        count = int(self.value)
        verb = "cell repeats" if count == 1 else "cells repeat"
        examples = ", ".join(f'"{value}" in {cells} cells' for value, cells in self.repeated)
        return f"column '{self.column}' is not unique: {count} {verb} an earlier value" + (
            f" ({examples})" if examples else ""
        )

    def _describe_unique_key(self) -> str:
        names = " + ".join(f"'{name}'" for name in self.key)
        skipped = ""
        if self.skipped:
            noun = (
                "row with a missing key cell was"
                if self.skipped == 1
                else ("rows with a missing key cell were")
            )
            skipped = f"; {self.skipped} {noun} skipped"
        if self.passed:
            return f"key {names} has no repeated values{skipped}"
        count = int(self.value)
        verb = "row repeats" if count == 1 else "rows repeat"
        examples = ", ".join(
            " + ".join(f'"{value}"' for value in values) + f" in {rows} rows"
            for values, rows in self.repeated_keys
        )
        return (
            f"key {names} is not unique: {count} {verb} an earlier key"
            + (f" ({examples})" if examples else "")
            + skipped
        )

    def _describe_missing_increase(self) -> str:
        if self.detail in _UNCOMPARABLE:
            return f"column '{self.column}' cannot be compared with the baseline ({self.detail})"
        if self.value > 0:
            change = f"rose {_fmt(self.value)} points"
        else:
            change = "did not rise"
        return (
            f"column '{self.column}' missing values {change} since the baseline "
            f"({self.detail}; limit {_fmt(self.limit)} points)"
        )

    def _describe_allowed_values(self) -> str:
        listed = ", ".join(self.allowed[:_MAX_LISTED])
        if len(self.allowed) > _MAX_LISTED:
            listed += f", ... ({len(self.allowed)} values)"
        if self.passed:
            return f"column '{self.column}' has only allowed values ({listed})"
        count = int(self.value)
        noun = "cell" if count == 1 else "cells"
        examples = ", ".join(
            f'"{value}" in {cells} cell' + ("s" if cells != 1 else "")
            for value, cells in self.unexpected
        )
        return (
            f"column '{self.column}' has {count} {noun} outside the allowed values ({listed})"
            + (f": {examples}" if examples else "")
        )

    def _describe_pattern(self) -> str:
        shown = code_span(self.pattern)
        if self.passed:
            return f"column '{self.column}' matches the pattern {shown}"
        count = int(self.value)
        noun = "cell that does" if count == 1 else "cells that do"
        examples = ", ".join(
            f'"{value}" in {cells} cell' + ("s" if cells != 1 else "")
            for value, cells in self.mismatched
        )
        return f"column '{self.column}' has {count} {noun} not match the pattern {shown}" + (
            f": {examples}" if examples else ""
        )

    def _describe_max_age(self) -> str:
        limit = format_duration(int(self.limit))
        if self.detail == _NO_VALUES:
            return f"column '{self.column}' has no values, so it has no newest value to check"
        if self.actual not in _AGE_TYPES:
            message = (
                f"column '{self.column}' is {self.actual}, an age needs date or datetime values"
            )
            return message + (f" ({self.detail})" if self.detail else "")
        if self.detail:  # values whose time cannot be placed without a guess
            return f"column '{self.column}' cannot be checked for its age ({self.detail})"
        if self.value < 0:
            ahead = format_duration(-int(self.value))
            return (
                f"column '{self.column}' is fresh: its newest value {self.newest} is {ahead} "
                f"ahead of the clock (limit {limit})"
            )
        state = "is fresh" if self.passed else "is stale"
        return (
            f"column '{self.column}' {state}: its newest value {self.newest} is "
            f"{format_duration(int(self.value))} old (limit {limit})"
        )

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


# Column types a --max-age check applies to.
_AGE_TYPES = {"date", "datetime"}
_NO_VALUES = "it has no values"

# Column types a range applies to, by the kind of its bounds. Dates and
# date-times apply to both temporal types; see docs/decisions/0003.
_RANGE_TYPES = {
    "int or float": {"int", "float"},
    "date": {"date", "datetime"},
    "datetime": {"date", "datetime"},
}


# CSV and check metadata can contain terminal escape/control characters.
# Render them as numeric references instead of silently passing them into
# Markdown job summaries. JSON representations remain completely unchanged.
_CONTROL_ENTITIES = {
    codepoint: f"&#{codepoint};"
    for codepoint in (*range(9), *range(10, 32), *range(127, 160))

}


def escape_control_chars(text: str) -> str:
    """Keep dangerous C0, DEL and C1 controls out; retain ordinary tabs."""
    return text.translate(_CONTROL_ENTITIES)


def code_span(text: str) -> str:
    """``text`` as one Markdown code span, so the backslashes of ``\\d`` or ``\\.`` show as written.

    The fence is one backtick longer than the longest run of backticks in
    ``text`` (padded with spaces when ``text`` starts or ends with one), and
    line breaks become spaces, so the span stays on one line.
    """
    text = escape_control_chars(text.replace("\r", " ").replace("\n", " "))
    longest = max((len(run) for run in re.findall("`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


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


@dataclass(frozen=True)
class TypeChangeRule:
    """A type change that ``schema_change_check`` tolerates (``--allow-type-change``).

    ``before`` and ``after`` are inferred column types (``COLUMN_TYPES``);
    ``column`` limits the rule to one column, ``None`` applies it to every
    column. The pair is matched exactly: ``int -> float`` says nothing about
    ``int -> string``.
    """

    before: str
    after: str
    column: str | None = None

    def __post_init__(self) -> None:
        for kind in (self.before, self.after):
            if kind not in COLUMN_TYPES:
                raise ValueError(
                    f"unknown column type {kind!r}; use one of {', '.join(COLUMN_TYPES)}"
                )
        if self.before == self.after:
            raise ValueError(f"{self.before}:{self.after} is not a type change")
        if self.column is not None and not self.column:
            raise ValueError("a type change rule needs a column name or None")

    def matches(self, change: TypeChange) -> bool:
        """Whether this rule tolerates ``change``."""
        return (
            change.before == self.before
            and change.after == self.after
            and (self.column is None or change.column == self.column)
        )

    def __str__(self) -> str:
        rule = f"{self.before}:{self.after}"
        return rule if self.column is None else f"{self.column}={rule}"


def _type_change(change: TypeChange) -> str:
    return f"'{change.column}' {change.before} -> {change.after}"


def _column_names(names: Iterable[str], parameter: str) -> tuple[str, ...]:
    """Validated, unique column names for ``schema_change_check`` (order kept)."""
    if isinstance(names, str):
        raise TypeError(f"{parameter} takes column names, not one string {names!r}")
    unique = tuple(dict.fromkeys(names))
    for name in unique:
        if not isinstance(name, str):
            raise TypeError(f"{parameter} takes column names, not {name!r}")
        if not name:
            raise ValueError(f"{parameter} takes non-empty column names")
    return unique


def schema_change_check(
    comparison: Comparison,
    allowed_type_changes: Iterable[TypeChangeRule] = (),
    allowed_added_columns: Iterable[str] = (),
    allowed_removed_columns: Iterable[str] = (),
) -> CheckResult:
    """A check that fails when columns were added, removed or changed type since the baseline.

    A type change matched by one of ``allowed_type_changes`` is tolerated:
    it is not counted in ``value`` and is listed in ``tolerated``. Likewise an
    added column named in ``allowed_added_columns`` (``tolerated_added``) and
    a removed column named in ``allowed_removed_columns``
    (``tolerated_removed``); names match exactly. Repeated rules and names
    count once.
    """
    rules = tuple(dict.fromkeys(allowed_type_changes))
    for rule in rules:
        if not isinstance(rule, TypeChangeRule):
            raise TypeError(f"allowed_type_changes takes TypeChangeRule items, not {rule!r}")
    allowed_added = _column_names(allowed_added_columns, "allowed_added_columns")
    allowed_removed = _column_names(allowed_removed_columns, "allowed_removed_columns")
    tolerated = tuple(
        change for change in comparison.type_changes if any(rule.matches(change) for rule in rules)
    )
    counted = [change for change in comparison.type_changes if change not in tolerated]
    tolerated_added = tuple(name for name in comparison.added_columns if name in allowed_added)
    tolerated_removed = tuple(
        name for name in comparison.removed_columns if name in allowed_removed
    )
    added = [name for name in comparison.added_columns if name not in tolerated_added]
    removed = [name for name in comparison.removed_columns if name not in tolerated_removed]
    parts = []
    if added:
        parts.append("added " + ", ".join(f"'{name}'" for name in added))
    if removed:
        parts.append("removed " + ", ".join(f"'{name}'" for name in removed))
    parts.extend(_type_change(change) for change in counted)
    changes = (
        comparison.schema_changes - len(tolerated) - len(tolerated_added) - len(tolerated_removed)
    )
    return CheckResult(
        check=CHECK_SCHEMA_CHANGE,
        column=None,
        limit=0,
        value=changes,
        passed=changes == 0,
        detail="; ".join(parts),
        allowed_rules=rules,
        tolerated=tolerated,
        allowed_added=allowed_added,
        tolerated_added=tolerated_added,
        allowed_removed=allowed_removed,
        tolerated_removed=tolerated_removed,
    )


def _limit(limit: float) -> Fraction:
    """A percentage limit as the exact decimal written (``0.1`` is 1/10, not a binary float)."""
    return Fraction(str(limit))


def _shown(value: Fraction) -> float:
    """A percentage for reports: 4 decimals, but never 0 for a value that is not 0."""
    rounded = round(float(value), 4)
    return rounded if rounded or not value else float(value)


def _share(missing: int, rows: int) -> Fraction:
    """Missing cells as an exact percentage of ``rows`` (0 for an empty file)."""
    return Fraction(100 * missing, rows) if rows else Fraction(0)


def row_drop_check(comparison: Comparison, max_drop: float) -> CheckResult:
    """A check that fails when the row count fell by more than ``max_drop`` % of the baseline's.

    More rows than the baseline, or a baseline without rows, is no drop. The
    comparison is exact (fractions of the row counts); a drop equal to the
    limit passes.
    """
    before, after = comparison.rows_before, comparison.rows_after
    drop = Fraction(100 * (before - after), before) if before > after else Fraction(0)
    return CheckResult(
        check=CHECK_ROW_DROP,
        column=None,
        limit=max_drop,
        value=_shown(drop),
        passed=drop <= _limit(max_drop),
        detail=f"{before} -> {after}",
    )


_DURATION_UNITS = (("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1))


def format_duration(seconds: int) -> str:
    """``seconds`` in words, every non-zero unit: ``9 days 4 hours``, ``0 seconds``."""
    parts = []
    for unit, size in _DURATION_UNITS:
        count, seconds = divmod(seconds, size)
        if count:
            parts.append(f"{count} {unit}" + ("s" if count != 1 else ""))
    return " ".join(parts) or "0 seconds"


def baseline_age_check(comparison: Comparison, max_age: int, now: datetime) -> CheckResult:
    """A check that fails when the baseline report is more than ``max_age`` seconds old.

    The age is ``now`` (an aware datetime) minus the baseline's
    ``generated_at`` stamp, written by ``--record-time``, in whole seconds;
    an age equal to the limit passes. A baseline without a stamp, or with
    one that is not a ``YYYY-MM-DDTHH:MM:SSZ`` time, fails and says why: the
    file's modification time is never used, since copying or downloading
    the file changes it. A stamp up to ``CLOCK_SKEW_TOLERANCE`` seconds in
    the future counts as 0 seconds old; later fails.
    """
    if isinstance(max_age, bool) or not isinstance(max_age, int):
        raise TypeError(f"max_age must be a whole number of seconds, not {max_age!r}")
    if max_age <= 0:
        raise ValueError(f"max_age must be positive, not {max_age}")
    if now.tzinfo is None:
        raise ValueError("now must be an aware datetime (with a UTC offset)")
    stamp = comparison.baseline_generated_at
    limit = format_duration(max_age)
    if stamp is None:
        return _age_problem(
            max_age, stamp, "the baseline has no 'generated_at' time (write it with --record-time)"
        )
    generated = parse_stamp(stamp)
    if generated is None:
        return _age_problem(
            max_age,
            stamp,
            f"the baseline's 'generated_at' is not a UTC time like 2026-10-16T04:06:00Z: {stamp!r}",
        )
    age = (now - generated) // timedelta(seconds=1)
    if age < -CLOCK_SKEW_TOLERANCE:
        return _age_problem(
            max_age,
            stamp,
            f"the baseline was generated in the future: {stamp} is {format_duration(-age)} "
            f"ahead of the clock ({format_stamp(now)})",
        )
    age = max(age, 0)
    return CheckResult(
        check=CHECK_BASELINE_AGE,
        column=None,
        limit=max_age,
        value=age,
        passed=age <= max_age,
        detail=f"the baseline is {format_duration(age)} old (generated {stamp}; limit {limit})",
        generated_at=stamp,
    )


def _age_problem(max_age: int, stamp: str | None, detail: str) -> CheckResult:
    """A failed ``baseline_age`` check whose age cannot be known."""
    return CheckResult(
        check=CHECK_BASELINE_AGE,
        column=None,
        limit=max_age,
        value=0,
        passed=False,
        detail=detail,
        generated_at=stamp,
    )


def missing_increase_checks(
    comparison: Comparison,
    max_increase: float | None,
    column_max_increase: Mapping[str, float] | None = None,
) -> list[CheckResult]:
    """One check per compared column: missing share rose by at most its limit, in points.

    ``max_increase`` applies to every column present in both reports;
    ``column_max_increase`` maps column names to their own limit, which
    overrides ``max_increase`` for that column and can be used without it
    (``max_increase`` is then ``None`` and only the named columns are
    checked). The share of missing cells is computed exactly from the counts
    of both reports (``Comparison.missing_counts``), so the rounded
    ``missing_pct`` never hides a rise just above the limit; a rise equal to
    the limit passes. A baseline column without a ``missing`` count fails and
    says why. Columns added since the baseline are not compared by
    ``max_increase``: they are schema changes. A column named in
    ``column_max_increase`` that cannot be compared (added since the
    baseline, removed from the file, or in neither report) fails and says
    why, after the compared columns, instead of being ignored.
    """
    limits = dict(column_max_increase or {})
    results = []
    for count in comparison.missing_counts:
        limit = limits.pop(count.column, max_increase)
        if limit is None:
            continue
        after = _share(count.after, comparison.rows_after)
        if count.before is None:
            results.append(_uncompared(count.column, limit, _NO_BASELINE_COUNT))
            continue
        before = _share(count.before, comparison.rows_before)
        rise = after - before
        results.append(
            CheckResult(
                check=CHECK_MISSING_INCREASE,
                column=count.column,
                limit=limit,
                value=_shown(rise),
                passed=rise <= _limit(limit),
                detail=f"{_fmt(_shown(before))}% -> {_fmt(_shown(after))}%",
            )
        )
    for name, limit in limits.items():  # named columns that were not compared
        if name in comparison.added_columns:
            detail = _NOT_IN_BASELINE
        elif name in comparison.removed_columns:
            detail = _NOT_IN_FILE
        else:
            detail = _IN_NEITHER
        results.append(_uncompared(name, limit, detail))
    return results


def _uncompared(column: str, limit: float, detail: str) -> CheckResult:
    """A failed ``missing_increase`` check for a column that cannot be compared."""
    return CheckResult(
        check=CHECK_MISSING_INCREASE,
        column=column,
        limit=limit,
        value=0,
        passed=False,
        detail=detail,
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


def _max_age_check(
    name: str, column: ColumnProfile, max_age: int, now: datetime, utc_offset: timedelta | None
) -> CheckResult:
    """The ``max_age`` check: the newest value of ``column`` is at most ``max_age`` seconds old.

    The age is ``now`` minus the newest value, in whole seconds. Values with a
    UTC offset are instants; values without one are placed at ``utc_offset``,
    and without it the check fails instead of guessing a time zone (ADR 0003,
    ADR 0009). A ``date`` column's newest day counts until its end; in a
    ``datetime`` column, a date without a time is midnight, as in ``--range``.
    A newest value ahead of the clock is ``value`` below 0 and passes.
    """
    newest = None if column.max is None else str(column.max)

    def result(passed: bool, value: int = 0, detail: str = "") -> CheckResult:
        return CheckResult(
            check=CHECK_MAX_AGE,
            column=name,
            limit=max_age,
            value=value,
            passed=passed,
            detail=detail,
            actual=column.type,
            newest=newest,
        )

    if column.distinct == 0:  # an empty column (reported as string): no data at all
        return result(False, detail=_NO_VALUES)
    if column.type not in _AGE_TYPES:
        hint = column.type_hint
        detail = ""
        if hint is not None and hint.type in _AGE_TYPES:
            noun = "value does" if hint.nonconforming == 1 else "values do"
            examples = ", ".join(f'"{v}"' for v in hint.examples)
            detail = f"{hint.nonconforming} {noun} not fit: {examples}"
        return result(False, detail=detail)
    if newest is None:  # a datetime column mixing values with and without an offset
        return result(False, detail="it mixes values with and without a UTC offset")
    moment = _moment(newest)
    if column.type == "date":
        moment += timedelta(days=1)  # the day lasts until the next midnight
    if moment.tzinfo is None:
        if utc_offset is None:
            return result(
                False,
                detail="its values have no UTC offset; give the offset the export writes its "
                "times in, such as --utc-offset=-04:00",
            )
        moment = moment.replace(tzinfo=timezone(utc_offset))
    age = (now - moment) // timedelta(seconds=1)
    return result(age <= max_age, value=age)


def _unique_check(name: str, column: ColumnProfile, rows: int) -> CheckResult:
    """A check that fails when ``column`` has a non-missing value more than once.

    Each column counts its stripped, non-missing values, and every cell is
    either missing or one of them, so the cells that repeat an earlier value
    are the non-missing cells minus the distinct values. The examples are the
    repeated values among the column's top values (none with ``top_n`` 0).
    """
    repeated = rows - column.missing - column.distinct
    return CheckResult(
        check=CHECK_UNIQUE,
        column=name,
        limit=0,
        value=repeated,
        passed=repeated <= 0,
        repeated=tuple((value, cells) for value, cells in column.top_values if cells > 1),
    )


def _allowed_values_check(domain: DomainProfile) -> CheckResult:
    """A check that fails when a non-missing cell holds a value outside ``domain.allowed``."""
    return CheckResult(
        check=CHECK_ALLOWED_VALUES,
        column=domain.column,
        limit=0,
        value=domain.unexpected,
        passed=domain.unexpected == 0,
        allowed=domain.allowed,
        unexpected=domain.examples,
    )


def _pattern_check(profile: PatternProfile) -> CheckResult:
    """A check that fails when a non-missing cell does not match ``profile.pattern``."""
    return CheckResult(
        check=CHECK_PATTERN,
        column=profile.column,
        limit=0,
        value=profile.mismatched,
        passed=profile.mismatched == 0,
        pattern=profile.pattern,
        mismatched=profile.examples,
    )


def _unique_key_check(key: KeyProfile) -> CheckResult:
    """A check that fails when two checked rows share the values of ``key``'s columns."""
    return CheckResult(
        check=CHECK_UNIQUE_KEY,
        column=None,
        limit=0,
        value=key.repeated,
        passed=key.repeated == 0,
        key=key.columns,
        repeated_keys=key.examples,
        skipped=key.skipped,
    )


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
    unique_columns: Iterable[str] = (),
    unique_keys: Iterable[Iterable[str]] = (),
    column_max_ages: Mapping[str, int] | None = None,
    now: datetime | None = None,
    utc_offset: timedelta | None = None,
    min_rows: int | None = None,
    allowed_values: Mapping[str, Iterable[str]] | None = None,
    patterns: Mapping[str, str] | None = None,
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

    ``unique_columns`` names columns that must not have a non-missing value
    more than once, such as an invoice number or a tracking code. Values
    compare as the report counts them: stripped of surrounding whitespace,
    case-sensitive, as text (``007`` and ``7`` differ); missing cells never
    repeat. The check's ``value`` is the number of cells that repeat an
    earlier value, exact also when they are not among the top values, and
    ``repeated`` lists the repeated top values. Unknown names fail as
    ``required_column``.

    ``unique_keys`` are composite keys, each a sequence of column names (an
    invoice number and a line number): two rows must not share the values of
    all of them. The report must have been built with the same keys
    (``profile_file(..., unique_keys=...)``), which measures them in the
    single pass (``Report.keys``); a key it lacks raises ``ValueError``. Key
    cells compare like ``unique_columns`` values; a row with a missing key
    cell is not checked and is counted in the check's ``skipped``. The
    check's ``value`` is the number of rows that repeat an earlier row's key,
    exact, and ``repeated_keys`` lists the first keys found repeated. A key
    may use columns left out of the profile by ``columns``, since rows are
    read whole. Unknown names fail as ``required_column``.

    ``column_max_ages`` maps column names to the most seconds their newest
    value may lie before ``now`` (an aware datetime, required with it), for
    exports that stopped being refreshed. Only ``date`` and ``datetime``
    columns qualify; a column of another type, or with no values, fails.
    Values with a UTC offset are compared as instants; values without one
    are taken at ``utc_offset`` (a ``timedelta``), and without it their
    check fails instead of guessing a time zone. A ``date`` column's newest
    day counts until its end. A newest value ahead of ``now`` passes, with a
    negative ``value``. Unknown names fail as ``required_column`` (ADR 0009).

    ``min_rows`` is the fewest data rows the file may have (``Report.rows``,
    the rows analyzed), at least 1: a file with only its header passes every
    other gate, since nothing in it is missing, repeated or out of range.

    ``allowed_values`` maps column names to the values their non-missing
    cells may hold, such as a status or currency code. The report must have
    been built with the same lists (``profile_file(..., allowed_values=...)``),
    which counts the cells outside them (``Report.domains``); a list it lacks
    raises ``ValueError``. Values compare stripped, case-sensitive, as text;
    the check's ``value`` is the exact number of cells outside the list and
    ``unexpected`` names the most frequent of their values. Unknown names fail
    as ``required_column``.

    ``patterns`` maps column names to regular expressions that every
    non-missing value must match as a whole (``re.fullmatch``), such as a
    postal code or a tax id format. As with ``allowed_values``, the report
    must have been built with the same patterns (``Report.patterns``); one it
    lacks raises ``ValueError``, and so does an empty or invalid pattern. The
    check's ``value`` is the exact number of cells that do not match and
    ``mismatched`` names the most frequent of their values. Unknown names
    fail as ``required_column``.

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
    if min_rows is not None:
        if isinstance(min_rows, bool) or not isinstance(min_rows, int) or min_rows < 1:
            raise ValueError(f"min_rows must be a whole number of at least 1, not {min_rows!r}")
        results.append(
            CheckResult(
                check=CHECK_MIN_ROWS,
                column=None,
                limit=min_rows,
                value=report.rows,
                passed=report.rows >= min_rows,
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
    unique = list(dict.fromkeys(unique_columns))
    gated = [*(column_max_missing or {}), *(column_types or {}), *(column_max_affixes or {})]
    max_ages = dict(column_max_ages or {})
    domains = {name: allowed_list(values) for name, values in (allowed_values or {}).items()}
    formats = dict(patterns or {})
    for pattern in formats.values():
        compile_pattern(pattern)  # ValueError when empty or invalid
    gated += [*(column_ranges or {}), *unique, *max_ages, *domains, *formats]
    unprofiled = [name for name in gated if name in present]
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
    for name in unique:
        column = by_name.get(name)
        if column is None:
            continue  # reported below as a missing required column
        results.append(_unique_check(name, column, report.rows))
    if max_ages:
        if now is None or now.tzinfo is None:
            raise ValueError("max_age checks need now, an aware datetime (with a UTC offset)")
        for name, max_age in max_ages.items():
            if isinstance(max_age, bool) or not isinstance(max_age, int) or max_age <= 0:
                raise ValueError(f"max age for column {name!r} must be a positive whole number")
            column = by_name.get(name)
            if column is None:
                continue  # reported below as a missing required column
            results.append(_max_age_check(name, column, max_age, now, utc_offset))
    measured_domains = {domain.column: domain for domain in report.domains}
    for name, allowed in domains.items():
        if name not in by_name:
            continue  # reported below as a missing required column
        domain = measured_domains.get(name)
        if domain is None or domain.allowed != allowed:
            raise ValueError(
                f"column {name!r} has an allowed_values check but the report was not "
                "profiled with the same list"
            )
        results.append(_allowed_values_check(domain))
    measured_patterns = {profile.column: profile for profile in report.patterns}
    for name, pattern in formats.items():
        if name not in by_name:
            continue  # reported below as a missing required column
        profile = measured_patterns.get(name)
        if profile is None or profile.pattern != pattern:
            raise ValueError(
                f"column {name!r} has a pattern check but the report was not "
                "profiled with the same pattern"
            )
        results.append(_pattern_check(profile))
    keys = list(dict.fromkeys(key_columns(key) for key in unique_keys))
    measured = {key.columns: key for key in report.keys}
    for columns in keys:
        if not present.issuperset(columns):
            continue  # the unknown names are reported below as missing required columns
        key = measured.get(columns)
        if key is None:
            names = ", ".join(columns)
            raise ValueError(f"key ({names}) has a unique_key check but was not profiled")
        results.append(_unique_key_check(key))
    key_names = [name for columns in keys for name in columns]
    unknown_limited = (
        name
        for name in [
            *column_limits,
            *required_types,
            *affix_limits,
            *ranges,
            *unique,
            *key_names,
            *max_ages,
            *domains,
            *formats,
        ]
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
