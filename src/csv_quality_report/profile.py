"""Compute per-column statistics and dataset-level duplicate count."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .inference import TYPE_FLOAT, TYPE_INT, infer_type
from .reader import Table

TOP_N = 3


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    type: str
    missing: int
    missing_pct: float
    distinct: int
    min: int | float | None
    max: int | float | None
    top_values: list[tuple[str, int]]


@dataclass(frozen=True)
class Report:
    rows: int
    duplicate_rows: int
    truncated: bool
    columns: list[ColumnProfile]


def _is_missing(cell: str) -> bool:
    return cell.strip() == ""


def _profile_column(name: str, cells: list[str]) -> ColumnProfile:
    total = len(cells)
    values = [c.strip() for c in cells if not _is_missing(c)]
    missing = total - len(values)
    col_type = infer_type(values)

    low: int | float | None = None
    high: int | float | None = None
    if values and col_type in (TYPE_INT, TYPE_FLOAT):
        nums = [int(v) if col_type == TYPE_INT else float(v) for v in values]
        low, high = min(nums), max(nums)

    counts = Counter(values)  # most_common is stable: ties keep first-seen order
    return ColumnProfile(
        name=name,
        type=col_type,
        missing=missing,
        missing_pct=round(100.0 * missing / total, 1) if total else 0.0,
        distinct=len(counts),
        min=low,
        max=high,
        top_values=counts.most_common(TOP_N),
    )


def build_report(table: Table) -> Report:
    """Profile every column of ``table``.

    ``duplicate_rows`` counts rows that exactly repeat an earlier row
    (total rows minus unique rows), comparing raw cell text.
    """
    columns = [
        _profile_column(name, [row[i] for row in table.rows])
        for i, name in enumerate(table.header)
    ]
    unique = len({tuple(row) for row in table.rows})
    return Report(
        rows=len(table.rows),
        duplicate_rows=len(table.rows) - unique,
        truncated=table.truncated,
        columns=columns,
    )
