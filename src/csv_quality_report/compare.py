"""Compare a report with a previous JSON report of the same source (``--baseline``).

Scheduled exports change without notice: a column is dropped or renamed, an
amount column starts arriving as text, a field that was always filled comes
back half empty. Comparing each run with the report of an earlier one makes
those changes visible, and ``--fail-on-schema-change`` stops a pipeline on
the ones that break consumers (columns added or removed, types changed).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import FileReadError
from .profile import Report


@dataclass(frozen=True)
class TypeChange:
    column: str
    before: str
    after: str


@dataclass(frozen=True)
class MissingChange:
    column: str
    before_pct: float
    after_pct: float


@dataclass(frozen=True)
class MissingCount:
    """Missing cells of a column in the baseline and in the current report.

    ``before`` is ``None`` when the baseline entry has no integer ``missing``
    count (a report not written by this tool), so drift gates can say so
    instead of guessing from the rounded ``missing_pct``.
    """

    column: str
    before: int | None
    after: int


@dataclass(frozen=True)
class Comparison:
    """What changed between a baseline report and the current one."""

    baseline_source: str  # the "source" recorded in the baseline report
    rows_before: int
    rows_after: int
    added_columns: tuple[str, ...]
    removed_columns: tuple[str, ...]
    type_changes: tuple[TypeChange, ...]
    missing_changes: tuple[MissingChange, ...]
    # Every column present in both reports, in the current report's order,
    # with exact counts for the drift gates (``--max-missing-increase``).
    missing_counts: tuple[MissingCount, ...] = ()
    # The baseline's "generated_at" stamp (--record-time), as written, or None
    # when it has none; a value that is not a string is kept as its JSON text
    # so --max-baseline-age can say it is not a time.
    baseline_generated_at: str | None = None

    @property
    def schema_changes(self) -> int:
        """Added and removed columns plus type changes: what breaks consumers."""
        return len(self.added_columns) + len(self.removed_columns) + len(self.type_changes)


def _baseline_columns(
    baseline: Mapping[str, Any], *, check_missing_rate: bool = False
) -> list[Mapping[str, Any]]:
    """Validate baseline column metadata and optionally verify rounded missing-rate consistency."""
    rows = baseline.get("rows")
    columns = baseline.get("columns")
    if (
        not isinstance(rows, int)
        or isinstance(rows, bool)
        or rows < 0
        or not isinstance(columns, list)
    ):
        raise ValueError("it has no 'rows' count and 'columns' list")
    names: set[str] = set()
    for column in columns:
        if not (
            isinstance(column, Mapping)
            and isinstance(column.get("name"), str)
            and isinstance(column.get("type"), str)
            and isinstance(column.get("missing_pct"), int | float)
            and not isinstance(column.get("missing_pct"), bool)
        ):
            raise ValueError("a column has no 'name', 'type' and 'missing_pct'")
        name = column["name"]
        if name in names:
            raise ValueError(f"duplicate baseline column name: {name!r}")
        names.add(name)
        missing_pct = column["missing_pct"]
        # Chained comparisons safely reject NaN, infinities, out-of-range
        # numbers and arbitrarily large JSON integers without float conversion.
        if not 0 <= missing_pct <= 100:
            raise ValueError(
                f"baseline column {name!r} has an invalid 'missing_pct' (expected 0 to 100)"
            )
        # Older third-party reports may omit 'missing' or provide an invalid
        # type; their exact-count drift check already treats it as unavailable.
        # A valid integer claiming more missing cells than rows, however, is
        # internally impossible and must not be used as a historical baseline.
        count = column.get("missing")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            if count > rows:
                raise ValueError(
                    f"baseline column {name!r} has more missing cells ({count}) than rows ({rows})"
                )
            # Native reports round percentages to one decimal place. Allow
            # half of that display step (plus floating-point tolerance) and
            # more precise third-party rates, but reject inconsistent rates.
            # Multiplying integer counts first avoids overflow on huge totals.
            expected_pct = 100 * count / rows if rows else 0.0
            if check_missing_rate and abs(missing_pct - expected_pct) > 0.05000000001:
                raise ValueError(
                    f"baseline column {name!r} has a 'missing_pct' inconsistent "
                    f"with its 'missing' count ({count} of {rows} rows)"
                )
    return columns


def compare_reports(
    baseline: Mapping[str, Any], report: Report, *, check_missing_rate: bool = False
) -> Comparison:
    """Compare ``report`` with ``baseline``, a JSON report of this tool loaded as a dict.

    ``check_missing_rate`` optionally checks that each exact baseline missing
    count agrees with its percentage within the original one-decimal display
    precision; disabled by default to preserve older report compatibility.

    Columns are matched by name. When ``report`` profiled only some columns
    (``--columns``), only those are compared, so a baseline of the whole
    file does not show the others as removed. Raises ``ValueError`` when
    ``baseline`` is not a report of this tool.
    """
    entries = _baseline_columns(baseline, check_missing_rate=check_missing_rate)
    before = {entry["name"]: entry for entry in entries}
    if report.selected_columns is not None:
        wanted = set(report.selected_columns)
        before = {name: entry for name, entry in before.items() if name in wanted}
    after = {column.name: column for column in report.columns}
    type_changes = tuple(
        TypeChange(name, before[name]["type"], column.type)
        for name, column in after.items()
        if name in before and before[name]["type"] != column.type
    )
    missing_changes = tuple(
        MissingChange(name, float(before[name]["missing_pct"]), column.missing_pct)
        for name, column in after.items()
        if name in before and before[name]["missing_pct"] != column.missing_pct
    )
    missing_counts = tuple(
        MissingCount(name, _missing_count(before[name]), column.missing)
        for name, column in after.items()
        if name in before
    )
    return Comparison(
        baseline_source=str(baseline.get("source", "")),
        rows_before=baseline["rows"],
        rows_after=report.rows,
        added_columns=tuple(name for name in after if name not in before),
        removed_columns=tuple(name for name in before if name not in after),
        type_changes=type_changes,
        missing_changes=missing_changes,
        missing_counts=missing_counts,
        baseline_generated_at=_stamp_text(baseline.get("generated_at")),
    )


def _stamp_text(value: Any) -> str | None:
    """The baseline's ``generated_at``: ``None`` when absent, JSON text when not a string."""
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value)


def _missing_count(entry: Mapping[str, Any]) -> int | None:
    """The baseline column's ``missing`` count, or ``None`` when it has no valid one."""
    count = entry.get("missing")
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        return count
    return None


def _unique_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate member names at every depth before a baseline is trusted.

    Standard JSON decoding silently keeps the *last* occurrence of a repeated
    name. In a historical quality report this can hide an earlier row count or
    missingness value and make drift comparisons unreliable.
    """
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"duplicate baseline JSON key: {name!r}")
        result[name] = value
    return result


def _reject_json_constant(text: str) -> float:
    """Reject Python's permissive NaN/Infinity extensions to standard JSON."""
    raise ValueError(f"non-standard baseline JSON numeric constant: {text}")


def _finite_json_float(text: str) -> float:
    """Do not silently turn a very large, valid JSON exponent into infinity."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"non-finite baseline JSON numeric value: {text}")
    return value


def load_baseline(path: Path, *, check_missing_rate: bool = False) -> dict[str, Any]:
    """Read baseline JSON, optionally checking counts against percentages (exit 3 on error)."""
    try:
        data = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_keys,
            parse_constant=_reject_json_constant,
            parse_float=_finite_json_float,
        )
    except OSError as exc:
        raise FileReadError(f"cannot read baseline '{path}': {exc.strerror or exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FileReadError(f"baseline '{path}' is not a JSON report ({exc})") from exc
    if not isinstance(data, dict):
        raise FileReadError(f"baseline '{path}' is not a csv-quality-report JSON report")
    try:
        _baseline_columns(data, check_missing_rate=check_missing_rate)
    except ValueError as exc:
        raise FileReadError(
            f"baseline '{path}' is not a csv-quality-report JSON report ({exc})"
        ) from exc
    return data
