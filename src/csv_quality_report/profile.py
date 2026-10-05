"""Compute per-column statistics and the duplicate-row count in one streaming pass."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import compress, islice, repeat
from pathlib import Path

from .inference import (
    TYPE_BOOL,
    TYPE_DATE,
    TYPE_DATETIME,
    TYPE_FLOAT,
    TYPE_INT,
    TYPE_STRING,
    infer_type,
    parse_datetime,
    parse_float,
    value_type,
)
from .reader import DEFAULT_ENCODING, Table, open_rows

TOP_N = 3  # default number of most frequent values per column (--top)
# A type hint needs at least 9/10 of the non-missing cells. Kept as integers:
# with floats, 10 * (1 - 0.9) is 0.9999999999999998 and exactly 90% would fail.
_HINT_SHARE_NUM, _HINT_SHARE_DEN = 9, 10
_HINT_EXAMPLES = 3  # nonconforming values shown in a type hint
_HINT_PROBE = 1_000  # distinct values checked one by one before bulk classification
# Candidate types for a hint, narrowest first, with the value types each covers.
_HINT_CANDIDATES = (
    (TYPE_BOOL, frozenset({TYPE_BOOL})),
    (TYPE_INT, frozenset({TYPE_INT})),
    (TYPE_FLOAT, frozenset({TYPE_INT, TYPE_FLOAT})),
    (TYPE_DATE, frozenset({TYPE_DATE})),
    (TYPE_DATETIME, frozenset({TYPE_DATE, TYPE_DATETIME})),
)
_BATCH_ROWS = 10_000  # rows profiled together; bounds the extra memory per batch


@dataclass(frozen=True)
class TypeHint:
    """A ``string`` column whose values mostly fit another type.

    ``conforming_pct`` is rounded down, so it never shows 100 while some
    values do not conform. ``examples`` are the most frequent nonconforming
    values (first seen on ties).
    """

    type: str
    conforming_pct: float
    nonconforming: int
    examples: tuple[str, ...]


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    type: str
    missing: int
    missing_pct: float
    distinct: int
    min: int | float | str | None  # str (original ISO 8601 text) for date/datetime
    max: int | float | str | None
    top_values: list[tuple[str, int]]
    untrimmed: int = 0  # non-missing cells with leading or trailing whitespace
    mean: float | None = None  # int and float columns only, 6 significant digits
    type_hint: TypeHint | None = None  # string columns that mostly fit another type


@dataclass(frozen=True)
class Report:
    rows: int
    duplicate_rows: int
    truncated: bool
    columns: list[ColumnProfile]
    delimiter: str = ","
    delimiter_detected: bool = False
    na_tokens: tuple[str, ...] = ()  # extra cell texts counted as missing
    top_n: int = TOP_N  # how many most frequent values each column lists
    compressed: bool = False  # the input was gzip-compressed
    untrimmed_columns: tuple[str, ...] = ()  # header names with surrounding whitespace
    encoding: str = DEFAULT_ENCODING  # codec used to decode the input


def _untrimmed_names(header: list[str]) -> tuple[str, ...]:
    """Header names, as reported, that have leading or trailing whitespace."""
    return tuple(name for name in header if name != name.strip())


def _row_digest(row: list[str]) -> bytes:
    """128-bit fingerprint of a row's exact cell texts.

    The cell lengths are written first, so cell boundaries are unambiguous:
    ``["a,b"]`` and ``["a", "b"]`` get different fingerprints.
    """
    key = ",".join([str(len(cell)) for cell in row]) + ":" + "".join(row)
    return hashlib.blake2b(key.encode("utf-8", "surrogatepass"), digest_size=16).digest()


def _datetime_range(values: Iterable[str]) -> tuple[str | None, str | None]:
    """Earliest and latest of ``values``, returned as their original text.

    Values with a UTC offset are compared as instants. If the column mixes
    values with and without an offset there is no honest ordering (a naive
    time could be in any zone), so no range is reported.
    """
    parsed = {v: parse_datetime(v) for v in values}
    instants = {v: d for v, d in parsed.items() if d is not None}
    if len({d.tzinfo is None for d in instants.values()}) != 1:
        return None, None
    return min(instants, key=instants.__getitem__), max(instants, key=instants.__getitem__)


def _mean(values: list[int] | list[float], counts: list[int]) -> float | None:
    """Mean of ``values`` weighted by ``counts``, rounded to 6 significant digits.

    Integers are summed exactly; floats with ``math.fsum`` over each value's
    share, which avoids both the drift of naive summation and overflow for
    values near the float limit. Returns ``None`` when the result cannot be
    represented as a finite float (integers with hundreds of digits).
    """
    total = sum(counts)
    try:
        if all(isinstance(v, int) for v in values):
            mean = sum(v * n for v, n in zip(values, counts, strict=True)) / total
        else:
            # Weight by share, not by count: v * n could overflow near 1e308.
            mean = math.fsum(v * (n / total) for v, n in zip(values, counts, strict=True))
    except OverflowError:
        return None
    return float(f"{mean:.6g}") if math.isfinite(mean) else None


def _type_hint(counts: Counter[str], decimal_comma: bool) -> TypeHint | None:
    """Dominant non-string type of a ``string`` column, if one covers 90% of its cells.

    Each distinct value is classified once and weighted by its count. The
    first ``_HINT_PROBE`` distinct values are checked one by one and the
    search stops as soon as plain-text cells exceed 10% of the total, since
    then no type can reach 90%: ordinary text columns are rejected almost for
    free. The rest is classified in bulk, with the counting done by
    ``itertools.compress`` and ``sum`` so it runs in C.
    """
    keys = list(counts)
    weights = list(counts.values())
    total = sum(weights)
    kinds: list[str] = []
    text_cells = 0
    for value, count in zip(keys[:_HINT_PROBE], weights, strict=False):
        kind = value_type(value, decimal_comma)
        if kind == TYPE_STRING:
            text_cells += count
            # More than 1/10 plain text: no type can reach 9/10.
            if text_cells * _HINT_SHARE_DEN > total * (_HINT_SHARE_DEN - _HINT_SHARE_NUM):
                return None
        kinds.append(kind)
    kinds.extend(map(value_type, keys[_HINT_PROBE:], repeat(decimal_comma)))
    cells = {kind: sum(compress(weights, map(kind.__eq__, kinds))) for kind in set(kinds)}
    best, members, covered = "", frozenset[str](), 0
    for candidate, covers in _HINT_CANDIDATES:
        share = sum(cells.get(kind, 0) for kind in covers)
        if share > covered:  # strict: the narrowest candidate wins ties
            best, members, covered = candidate, covers, share
    if not best or covered * _HINT_SHARE_DEN < total * _HINT_SHARE_NUM or covered == total:
        return None
    others = frozenset(cells) - members
    stray = sorted(
        compress(zip(keys, weights, strict=True), map(others.__contains__, kinds)),
        key=lambda item: -item[1],  # stable: first-seen order on ties
    )
    return TypeHint(
        type=best,
        conforming_pct=math.floor(10_000 * covered / total) / 100,
        nonconforming=total - covered,
        examples=tuple(v for v, _ in stray[:_HINT_EXAMPLES]),
    )


class _ColumnAccumulator:
    """Statistics for one column: missing count and value frequencies.

    Memory grows with the number of distinct values, not with the row count.
    """

    __slots__ = ("counts", "missing", "name", "untrimmed")

    def __init__(self, name: str) -> None:
        self.name = name
        self.missing = 0
        self.untrimmed = 0
        self.counts: Counter[str] = Counter()

    def strip_counts(self, na: set[str]) -> None:
        """Turn raw cell-text counts into stripped-value counts.

        The pass counts cells exactly as read; this merges them by stripped
        text once per distinct value, counting as ``untrimmed`` the non-missing
        cells that had surrounding whitespace, then moves missing cells (empty
        or in ``na``) out of the counter. First-seen order, which decides ties
        in top values, is kept: each stripped value takes the position of its
        first raw spelling.
        """
        raw = self.counts
        if any(key != key.strip() for key in raw):
            merged: Counter[str] = Counter()
            for key, count in raw.items():
                value = key.strip()
                merged[value] += count
                if value != key and value not in na:
                    self.untrimmed += count
            self.counts = merged
        self.missing = sum(self.counts.pop(token, 0) for token in na)

    def finish(self, total: int, decimal_comma: bool, top_n: int = TOP_N) -> ColumnProfile:
        # Inference, min and max only depend on which values occur, so looking
        # at distinct values gives the same answer as looking at every cell.
        distinct = self.counts.keys()
        col_type = infer_type(distinct, decimal_comma)
        low: int | float | str | None = None
        high: int | float | str | None = None
        mean: float | None = None
        if distinct and col_type in (TYPE_INT, TYPE_FLOAT):
            nums = [
                int(v) if col_type == TYPE_INT else parse_float(v, decimal_comma) for v in distinct
            ]
            low, high = min(nums), max(nums)
            mean = _mean(nums, list(self.counts.values()))
        elif distinct and col_type == TYPE_DATE:
            # Inference guarantees strict YYYY-MM-DD, whose text order is date order.
            low, high = min(distinct), max(distinct)
        elif distinct and col_type == TYPE_DATETIME:
            low, high = _datetime_range(distinct)
        return ColumnProfile(
            name=self.name,
            type=col_type,
            missing=self.missing,
            missing_pct=round(100.0 * self.missing / total, 1) if total else 0.0,
            distinct=len(self.counts),
            min=low,
            max=high,
            # most_common is stable: ties keep first-seen order.
            top_values=self.counts.most_common(top_n),
            untrimmed=self.untrimmed,
            mean=mean,
            type_hint=_type_hint(self.counts, decimal_comma) if col_type == TYPE_STRING else None,
        )


@dataclass(frozen=True)
class _Profiled:
    columns: list[ColumnProfile]
    rows: int
    duplicate_rows: int


def profile_rows(
    header: list[str],
    rows: Iterable[list[str]],
    decimal_comma: bool = False,
    na_tokens: Iterable[str] = (),
    top_n: int = TOP_N,
) -> _Profiled:
    """Profile ``rows`` in a single pass; each row must have ``len(header)`` cells.

    Cells whose stripped text is one of ``na_tokens`` count as missing, like
    empty cells. They are removed from the counters once, after the pass, so
    they cost nothing per row.

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
    # Cells are counted as read; stripping, untrimmed counts and missing cells
    # are resolved afterwards, once per distinct value (see strip_counts).
    # Only one batch is held in memory at a time.
    it = iter(rows)
    while batch := list(islice(it, _BATCH_ROWS)):
        total += len(batch)
        seen.update(map(_row_digest, batch))
        for counter, column in zip(counters, zip(*batch, strict=True), strict=True):
            counter.update(column)
    na = {token.strip() for token in na_tokens} | {""}
    for acc in columns:
        acc.strip_counts(na)
    return _Profiled(
        columns=[acc.finish(total, decimal_comma, top_n) for acc in columns],
        rows=total,
        duplicate_rows=total - len(seen),
    )


def build_report(
    table: Table,
    decimal_comma: bool = False,
    na_tokens: tuple[str, ...] = (),
    top_n: int = TOP_N,
) -> Report:
    """Profile every column of an in-memory ``table``.

    ``decimal_comma`` makes float inference expect ``,`` as the decimal mark;
    ``na_tokens`` are extra cell texts counted as missing; ``top_n`` is how
    many most frequent values each column lists.
    """
    result = profile_rows(table.header, table.rows, decimal_comma, na_tokens, top_n)
    return Report(
        rows=result.rows,
        duplicate_rows=result.duplicate_rows,
        truncated=table.truncated,
        columns=result.columns,
        delimiter=table.delimiter,
        delimiter_detected=table.delimiter_detected,
        na_tokens=na_tokens,
        top_n=top_n,
        compressed=table.compressed,
        untrimmed_columns=_untrimmed_names(table.header),
        encoding=table.encoding,
    )


def profile_file(
    path: Path,
    max_rows: int | None = None,
    delimiter: str = ",",
    decimal_comma: bool = False,
    na_tokens: tuple[str, ...] = (),
    top_n: int = TOP_N,
    encoding: str = DEFAULT_ENCODING,
) -> Report:
    """Stream ``path`` and profile it without loading the whole file into memory.

    Same rules and errors as ``reader.open_rows``; same result as
    ``build_report(read_table(...))``.
    """
    with open_rows(path, max_rows=max_rows, delimiter=delimiter, encoding=encoding) as stream:
        result = profile_rows(stream.header, stream, decimal_comma, na_tokens, top_n)
        return Report(
            rows=result.rows,
            duplicate_rows=result.duplicate_rows,
            truncated=stream.truncated,
            columns=result.columns,
            delimiter=stream.delimiter,
            delimiter_detected=stream.delimiter_detected,
            na_tokens=na_tokens,
            top_n=top_n,
            compressed=stream.compressed,
            untrimmed_columns=_untrimmed_names(stream.header),
            encoding=stream.encoding,
        )
