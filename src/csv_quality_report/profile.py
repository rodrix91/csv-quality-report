"""Compute per-column statistics and the duplicate-row count in one streaming pass."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from .inference import TYPE_FLOAT, TYPE_INT, infer_type, parse_float
from .reader import Table, open_rows

TOP_N = 3
_BATCH_ROWS = 10_000  # rows profiled together; bounds the extra memory per batch


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
    delimiter: str = ","
    delimiter_detected: bool = False


def _row_digest(row: list[str]) -> bytes:
    """128-bit fingerprint of a row's exact cell texts.

    The cell lengths are written first, so cell boundaries are unambiguous:
    ``["a,b"]`` and ``["a", "b"]`` get different fingerprints.
    """
    key = ",".join([str(len(cell)) for cell in row]) + ":" + "".join(row)
    return hashlib.blake2b(key.encode("utf-8", "surrogatepass"), digest_size=16).digest()


class _ColumnAccumulator:
    """Statistics for one column: missing count and value frequencies.

    Memory grows with the number of distinct values, not with the row count.
    """

    __slots__ = ("counts", "missing", "name")

    def __init__(self, name: str) -> None:
        self.name = name
        self.missing = 0
        self.counts: Counter[str] = Counter()

    def finish(self, total: int, decimal_comma: bool) -> ColumnProfile:
        # Inference, min and max only depend on which values occur, so looking
        # at distinct values gives the same answer as looking at every cell.
        distinct = self.counts.keys()
        col_type = infer_type(distinct, decimal_comma)
        low: int | float | None = None
        high: int | float | None = None
        if distinct and col_type in (TYPE_INT, TYPE_FLOAT):
            nums = [
                int(v) if col_type == TYPE_INT else parse_float(v, decimal_comma) for v in distinct
            ]
            low, high = min(nums), max(nums)
        return ColumnProfile(
            name=self.name,
            type=col_type,
            missing=self.missing,
            missing_pct=round(100.0 * self.missing / total, 1) if total else 0.0,
            distinct=len(self.counts),
            min=low,
            max=high,
            # most_common is stable: ties keep first-seen order.
            top_values=self.counts.most_common(TOP_N),
        )


@dataclass(frozen=True)
class _Profiled:
    columns: list[ColumnProfile]
    rows: int
    duplicate_rows: int


def profile_rows(
    header: list[str], rows: Iterable[list[str]], decimal_comma: bool = False
) -> _Profiled:
    """Profile ``rows`` in a single pass; each row must have ``len(header)`` cells.

    ``duplicate_rows`` counts rows that exactly repeat an earlier row. Rows are
    compared by a 128-bit BLAKE2b fingerprint of their cell texts instead of
    being stored, so a false match would need a hash collision (probability
    below 1e-20 even for billions of rows).
    """
    columns = [_ColumnAccumulator(name) for name in header]
    counters = [acc.counts for acc in columns]
    seen: set[bytes] = set()
    total = 0
    # Work on batches of rows transposed into columns, so counting runs inside
    # Counter.update (implemented in C) instead of one Python step per cell.
    # Missing cells are counted under the key "" and moved out afterwards.
    # Only one batch is held in memory at a time.
    it = iter(rows)
    while batch := list(islice(it, _BATCH_ROWS)):
        total += len(batch)
        seen.update(map(_row_digest, batch))
        for counter, column in zip(counters, zip(*batch, strict=True), strict=True):
            counter.update(map(str.strip, column))
    for acc in columns:
        acc.missing = acc.counts.pop("", 0)
    return _Profiled(
        columns=[acc.finish(total, decimal_comma) for acc in columns],
        rows=total,
        duplicate_rows=total - len(seen),
    )


def build_report(table: Table, decimal_comma: bool = False) -> Report:
    """Profile every column of an in-memory ``table``.

    ``decimal_comma`` makes float inference expect ``,`` as the decimal mark.
    """
    result = profile_rows(table.header, table.rows, decimal_comma)
    return Report(
        rows=result.rows,
        duplicate_rows=result.duplicate_rows,
        truncated=table.truncated,
        columns=result.columns,
        delimiter=table.delimiter,
        delimiter_detected=table.delimiter_detected,
    )


def profile_file(
    path: Path,
    max_rows: int | None = None,
    delimiter: str = ",",
    decimal_comma: bool = False,
) -> Report:
    """Stream ``path`` and profile it without loading the whole file into memory.

    Same rules and errors as ``reader.open_rows``; same result as
    ``build_report(read_table(...))``.
    """
    with open_rows(path, max_rows=max_rows, delimiter=delimiter) as stream:
        result = profile_rows(stream.header, stream, decimal_comma)
        return Report(
            rows=result.rows,
            duplicate_rows=result.duplicate_rows,
            truncated=stream.truncated,
            columns=result.columns,
            delimiter=stream.delimiter,
            delimiter_detected=stream.delimiter_detected,
        )
