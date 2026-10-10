"""Compare a report with a previous JSON report of the same source (``--baseline``).

Scheduled exports change without notice: a column is dropped or renamed, an
amount column starts arriving as text, a field that was always filled comes
back half empty. Comparing each run with the report of an earlier one makes
those changes visible, and ``--fail-on-schema-change`` stops a pipeline on
the ones that break consumers (columns added or removed, types changed).
"""

from __future__ import annotations

import json
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

    @property
    def schema_changes(self) -> int:
        """Added and removed columns plus type changes: what breaks consumers."""
        return len(self.added_columns) + len(self.removed_columns) + len(self.type_changes)


def _baseline_columns(baseline: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The column entries of a baseline report, validated; ``ValueError`` otherwise."""
    rows = baseline.get("rows")
    columns = baseline.get("columns")
    if not isinstance(rows, int) or isinstance(rows, bool) or not isinstance(columns, list):
        raise ValueError("it has no 'rows' count and 'columns' list")
    for column in columns:
        if not (
            isinstance(column, Mapping)
            and isinstance(column.get("name"), str)
            and isinstance(column.get("type"), str)
            and isinstance(column.get("missing_pct"), int | float)
            and not isinstance(column.get("missing_pct"), bool)
        ):
            raise ValueError("a column has no 'name', 'type' and 'missing_pct'")
    return columns


def compare_reports(baseline: Mapping[str, Any], report: Report) -> Comparison:
    """Compare ``report`` with ``baseline``, a JSON report of this tool loaded as a dict.

    Columns are matched by name. When ``report`` profiled only some columns
    (``--columns``), only those are compared, so a baseline of the whole
    file does not show the others as removed. Raises ``ValueError`` when
    ``baseline`` is not a report of this tool.
    """
    entries = _baseline_columns(baseline)
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
    )


def _missing_count(entry: Mapping[str, Any]) -> int | None:
    """The baseline column's ``missing`` count, or ``None`` when it has no valid one."""
    count = entry.get("missing")
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        return count
    return None


def load_baseline(path: Path) -> dict[str, Any]:
    """Read a baseline JSON report; ``FileReadError`` (exit code 3) when it is unusable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileReadError(f"cannot read baseline '{path}': {exc.strerror or exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FileReadError(f"baseline '{path}' is not a JSON report ({exc})") from exc
    if not isinstance(data, dict):
        raise FileReadError(f"baseline '{path}' is not a csv-quality-report JSON report")
    try:
        _baseline_columns(data)
    except ValueError as exc:
        raise FileReadError(
            f"baseline '{path}' is not a csv-quality-report JSON report ({exc})"
        ) from exc
    return data
