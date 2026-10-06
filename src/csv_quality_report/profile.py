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
    BoolWords,
    accounting_negative,
    bool_word_map,
    check_date_order,
    check_number_affixes,
    check_thousands,
    infer_type,
    normalize_bool,
    normalize_date,
    parse_datetime,
    parse_float,
    split_number_affix,
    strip_thousands,
    value_type,
)
from .reader import DEFAULT_ENCODING, RowStream, Table, open_rows

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
    # str for date/datetime: the ISO 8601 text as written, or as rewritten from
    # --date-order (``05/10/2026`` is reported as ``2026-10-05``)
    min: int | float | str | None
    max: int | float | str | None
    top_values: list[tuple[str, int]]
    untrimmed: int = 0  # non-missing cells with leading or trailing whitespace
    mean: float | None = None  # int and float columns only, 6 significant digits
    type_hint: TypeHint | None = None  # string columns that mostly fit another type
    min_length: int | None = None  # shortest non-missing stripped value, in characters
    max_length: int | None = None  # longest non-missing stripped value, in characters
    # (affix, cells) for --number-affix texts removed from this column's numbers,
    # most frequent first; several affixes can mean mixed currencies or units
    affixes: tuple[tuple[str, int], ...] = ()


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
    thousands: str | None = None  # thousands separator given (".", "," or " ")
    date_order: str | None = None  # order of non-ISO dates given ("dmy", "mdy" or "ymd")
    bool_words: BoolWords = ()  # extra (true, false) word pairs, as given
    sep_line: bool = False  # the input started with an Excel "sep=" line, which was skipped
    number_affixes: tuple[str, ...] = ()  # --number-affix texts, as validated
    accounting_negatives: bool = False  # (1.234,56) and 1.234,56- were read as negative


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


@dataclass(frozen=True)
class _Rules:
    """The validated reading rules that rewrite values before inference.

    Built once per run by ``_reading_rules``; every rewrite is applied once per
    distinct value, never per cell.
    """

    decimal_comma: bool = False
    thousands: str | None = None
    date_order: str | None = None
    bool_map: dict[str, str] | None = None
    affixes: tuple[str, ...] = ()  # longest first
    accounting: bool = False

    @property
    def rewrites(self) -> bool:
        """True when some rule changes values before inference."""
        return (
            self.thousands is not None
            or self.date_order is not None
            or self.bool_map is not None
            or bool(self.affixes)
            or self.accounting
        )


_NO_RULES = _Rules()  # plain reading: no rewrites before inference


def _reading_rules(
    decimal_comma: bool,
    thousands: str | None,
    date_order: str | None,
    bool_words: BoolWords,
    number_affixes: tuple[str, ...],
    accounting_negatives: bool,
) -> _Rules:
    """Validate the reading options; ``ValueError`` when unsupported or contradictory."""
    check_thousands(thousands, decimal_comma)
    check_date_order(date_order)
    return _Rules(
        decimal_comma=decimal_comma,
        thousands=thousands,
        date_order=date_order,
        bool_map=bool_word_map(bool_words) if bool_words else None,
        # Longer affixes first: when two would both leave a number, the longer wins.
        affixes=tuple(sorted(check_number_affixes(number_affixes), key=len, reverse=True)),
        accounting=accounting_negatives,
    )


def _signed(values: Iterable[str], rules: _Rules) -> list[str]:
    """``values`` with accounting negatives (``(5)``, ``5-``) given a leading minus."""
    return [
        accounting_negative(v, rules.affixes, rules.decimal_comma, rules.thousands) for v in values
    ]


def _normalized(values: Iterable[str], rules: _Rules) -> list[str]:
    """``values``, already without affixes, with thousands, dates and booleans rewritten.

    These rewrites never apply to the same value (a grouped number has
    three-digit groups, a date a one- or two-digit middle part, and boolean
    words cannot be numbers or dates), so their order does not matter.
    """
    plain = list(values)
    if rules.thousands is not None:
        plain = [strip_thousands(v, rules.thousands, rules.decimal_comma) for v in plain]
    if rules.date_order is not None:
        plain = [normalize_date(v, rules.date_order) for v in plain]
    if rules.bool_map is not None:
        plain = [normalize_bool(v, rules.bool_map) for v in plain]
    return plain


def _plain_values(values: Iterable[str], rules: _Rules) -> list[str]:
    """``values`` as inference reads them: numbers without their affixes and
    thousands separators, dates rewritten as ISO 8601 and boolean words as
    true/false, when those options are given.

    Accounting negatives are rewritten with a leading minus first; then
    affixes are removed, only from values that are then numbers.
    """
    plain = _signed(values, rules) if rules.accounting else list(values)
    if rules.affixes:
        plain = [
            split_number_affix(v, rules.affixes, rules.decimal_comma, rules.thousands)[0]
            for v in plain
        ]
    return _normalized(plain, rules)


def _type_hint(counts: Counter[str], rules: _Rules) -> TypeHint | None:
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
    # Classify values in their plain form (numbers without affixes or
    # thousands separators, dates in ISO form), but report strays as written.
    plain = _plain_values(keys, rules)
    decimal_comma = rules.decimal_comma
    total = sum(weights)
    kinds: list[str] = []
    text_cells = 0
    for value, count in zip(plain[:_HINT_PROBE], weights, strict=False):
        kind = value_type(value, decimal_comma)
        if kind == TYPE_STRING:
            text_cells += count
            # More than 1/10 plain text: no type can reach 9/10.
            if text_cells * _HINT_SHARE_DEN > total * (_HINT_SHARE_DEN - _HINT_SHARE_NUM):
                return None
        kinds.append(kind)
    kinds.extend(map(value_type, plain[_HINT_PROBE:], repeat(decimal_comma)))
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


def _split_affixes(
    values: Iterable[str], counts: Iterable[int], rules: _Rules
) -> tuple[list[str], tuple[tuple[str, int], ...]]:
    """Distinct ``values`` without their affixes, and the cells per removed affix.

    ``counts`` are the cells of each value, in the same order. The values
    keep their order; the affixes are listed most frequent first (first seen
    on ties). One pass, without an intermediate list of pairs, so the extra
    memory is one string per distinct value.
    """
    numbers: list[str] = []
    found: Counter[str] = Counter()
    for value, count in zip(values, counts, strict=True):
        number, affix = split_number_affix(
            value, rules.affixes, rules.decimal_comma, rules.thousands
        )
        numbers.append(number)
        if affix is not None:
            found[affix] += count
    return numbers, tuple(found.most_common())


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

    def finish(self, total: int, top_n: int = TOP_N, rules: _Rules = _NO_RULES) -> ColumnProfile:
        decimal_comma = rules.decimal_comma
        # Inference, min and max only depend on which values occur, so looking
        # at distinct values gives the same answer as looking at every cell.
        distinct = self.counts.keys()
        # With reading rules, values are inferred and measured in their plain
        # form (1234,5, 2026-10-05, true); top values and lengths keep the
        # text as written. Accounting negatives get a leading minus first, so
        # their affixes are found too; affixes are split once, in one pass
        # that also counts them.
        values: Iterable[str] = distinct
        affix_counts: tuple[tuple[str, int], ...] = ()
        if rules.rewrites:
            signed = _signed(distinct, rules) if rules.accounting else distinct
            if rules.affixes:
                signed, affix_counts = _split_affixes(signed, self.counts.values(), rules)
            values = _normalized(signed, rules)
        col_type = infer_type(values, decimal_comma)
        low: int | float | str | None = None
        high: int | float | str | None = None
        mean: float | None = None
        if distinct and col_type in (TYPE_INT, TYPE_FLOAT):
            nums = [
                int(v) if col_type == TYPE_INT else parse_float(v, decimal_comma) for v in values
            ]
            low, high = min(nums), max(nums)
            mean = _mean(nums, list(self.counts.values()))
        elif distinct and col_type == TYPE_DATE:
            # Inference guarantees strict YYYY-MM-DD, whose text order is date order.
            low, high = min(values), max(values)
        elif distinct and col_type == TYPE_DATETIME:
            low, high = _datetime_range(values)
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
            type_hint=_type_hint(self.counts, rules) if col_type == TYPE_STRING else None,
            min_length=min(map(len, distinct)) if distinct else None,
            max_length=max(map(len, distinct)) if distinct else None,
            affixes=affix_counts,
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
    thousands: str | None = None,
    date_order: str | None = None,
    bool_words: BoolWords = (),
    number_affixes: tuple[str, ...] = (),
    accounting_negatives: bool = False,
) -> _Profiled:
    """Profile ``rows`` in a single pass; each row must have ``len(header)`` cells.

    Cells whose stripped text is one of ``na_tokens`` count as missing, like
    empty cells. They are removed from the counters once, after the pass, so
    they cost nothing per row.

    ``duplicate_rows`` counts rows that exactly repeat an earlier row. Rows are
    compared by a 128-bit BLAKE2b fingerprint of their cell texts instead of
    being stored, so a false match would need a hash collision (probability
    below 1e-20 even for billions of rows).

    ``thousands``, ``date_order``, ``bool_words`` and ``number_affixes`` are
    validated before any row is read and raise ``ValueError`` when unsupported
    or contradictory.
    """
    rules = _reading_rules(
        decimal_comma, thousands, date_order, bool_words, number_affixes, accounting_negatives
    )
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
        columns=[acc.finish(total, top_n, rules) for acc in columns],
        rows=total,
        duplicate_rows=total - len(seen),
    )


def _report(
    result: _Profiled,
    source: Table | RowStream,
    na_tokens: tuple[str, ...],
    top_n: int,
    thousands: str | None,
    date_order: str | None,
    bool_words: BoolWords,
    number_affixes: tuple[str, ...],
    accounting_negatives: bool,
) -> Report:
    """The ``Report`` of a profiled ``Table`` or ``RowStream`` and the options used."""
    return Report(
        rows=result.rows,
        duplicate_rows=result.duplicate_rows,
        truncated=source.truncated,
        columns=result.columns,
        delimiter=source.delimiter,
        delimiter_detected=source.delimiter_detected,
        na_tokens=na_tokens,
        top_n=top_n,
        compressed=source.compressed,
        untrimmed_columns=_untrimmed_names(source.header),
        encoding=source.encoding,
        sep_line=source.sep_line,
        thousands=thousands,
        date_order=date_order,
        bool_words=bool_words,
        number_affixes=check_number_affixes(number_affixes),
        accounting_negatives=accounting_negatives,
    )


def build_report(
    table: Table,
    decimal_comma: bool = False,
    na_tokens: tuple[str, ...] = (),
    top_n: int = TOP_N,
    thousands: str | None = None,
    date_order: str | None = None,
    bool_words: BoolWords = (),
    number_affixes: tuple[str, ...] = (),
    accounting_negatives: bool = False,
) -> Report:
    """Profile every column of an in-memory ``table``.

    ``decimal_comma`` makes float inference expect ``,`` as the decimal mark;
    ``na_tokens`` are extra cell texts counted as missing; ``top_n`` is how
    many most frequent values each column lists; ``thousands`` is the
    thousands separator of numbers; ``date_order`` (``"dmy"``, ``"mdy"`` or
    ``"ymd"``) reads dates such as ``05/10/2026`` in that order;
    ``bool_words`` are extra ``(true, false)`` word pairs such as
    ``("sí", "no")``; ``number_affixes`` are texts such as ``"$"`` or ``"kg"``
    removed from around numbers; ``accounting_negatives`` reads ``(1.234,56)``
    and ``1.234,56-`` as negative numbers.
    """
    result = profile_rows(
        table.header,
        table.rows,
        decimal_comma,
        na_tokens,
        top_n,
        thousands,
        date_order,
        bool_words,
        number_affixes,
        accounting_negatives,
    )
    return _report(
        result,
        table,
        na_tokens,
        top_n,
        thousands,
        date_order,
        bool_words,
        number_affixes,
        accounting_negatives,
    )


def profile_file(
    path: Path,
    max_rows: int | None = None,
    delimiter: str = ",",
    decimal_comma: bool = False,
    na_tokens: tuple[str, ...] = (),
    top_n: int = TOP_N,
    encoding: str = DEFAULT_ENCODING,
    max_field_size: int | None = None,
    thousands: str | None = None,
    date_order: str | None = None,
    bool_words: BoolWords = (),
    number_affixes: tuple[str, ...] = (),
    accounting_negatives: bool = False,
) -> Report:
    """Stream ``path`` and profile it without loading the whole file into memory.

    Same rules and errors as ``reader.open_rows``; same result as
    ``build_report(read_table(...))``.
    """
    with open_rows(
        path,
        max_rows=max_rows,
        delimiter=delimiter,
        encoding=encoding,
        max_field_size=max_field_size,
    ) as stream:
        result = profile_rows(
            stream.header,
            stream,
            decimal_comma,
            na_tokens,
            top_n,
            thousands,
            date_order,
            bool_words,
            number_affixes,
            accounting_negatives,
        )
        return _report(
            result,
            stream,
            na_tokens,
            top_n,
            thousands,
            date_order,
            bool_words,
            number_affixes,
            accounting_negatives,
        )
