"""Compute per-column statistics and the duplicate-row count in one streaming pass."""

from __future__ import annotations

import hashlib
import heapq
import math
import re
from collections import Counter, deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import compress, islice, repeat
from operator import itemgetter
from typing import Any
from unicodedata import normalize

from .errors import ColumnSelectionError
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
    check_month_names,
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
from .reader import DEFAULT_ENCODING, PathArg, RowStream, Table, open_rows

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
class KeyProfile:
    """How unique a composite key (``--unique-key``) is over the rows read.

    Key cells compare as the report counts values: stripped of surrounding
    whitespace, case-sensitive, as text. A row with a missing key cell (empty
    or an ``na_tokens`` text) is not checked and counts as ``skipped``.
    ``repeated`` is the number of checked rows whose key equals an earlier
    row's key, exact for any number of rows. ``examples`` are the first
    ``top_n`` keys found repeated, with the rows that have each one, most
    rows first (first repeated first on ties); they are only a sample of the
    repeated keys, not the most repeated ones.
    """

    columns: tuple[str, ...]
    checked: int  # rows whose key cells are all present
    skipped: int  # rows with a missing key cell
    repeated: int  # checked rows whose key equals an earlier row's key
    examples: tuple[tuple[tuple[str, ...], int], ...] = ()  # (key values, rows)


@dataclass(frozen=True)
class DomainProfile:
    """Which values of a column fall outside an allowed list (``--allowed-values``).

    Values compare as the report counts them: stripped of surrounding
    whitespace, case-sensitive, as text; missing cells are not checked.
    ``unexpected`` is the exact number of non-missing cells whose value is
    not in ``allowed``; ``examples`` are the most frequent of those values,
    up to ``top_n``, with their cells (first seen on ties).
    """

    column: str
    allowed: tuple[str, ...]
    unexpected: int
    examples: tuple[tuple[str, int], ...] = ()


def allowed_list(values: Iterable[str]) -> tuple[str, ...]:
    """``values`` stripped, without repeats, in order; ``ValueError`` if one is empty or none."""
    listed = tuple(dict.fromkeys(value.strip() for value in values))
    if not listed or "" in listed:
        raise ValueError("an allowed-values list needs at least one value and no empty ones")
    return listed


@dataclass(frozen=True)
class PatternProfile:
    """Which values of a column do not match a regular expression (``--pattern``).

    Values are matched as the report counts them: stripped of surrounding
    whitespace, as text, with ``re.fullmatch`` (the whole value must match);
    missing cells are not checked. ``mismatched`` is the exact number of
    non-missing cells whose value does not match ``pattern``; ``examples``
    are the most frequent of those values, up to ``top_n``, with their cells
    (first seen on ties).
    """

    column: str
    pattern: str
    mismatched: int
    examples: tuple[tuple[str, int], ...] = ()


def check_na_ignore_case(na_ignore_case: bool, na_tokens: Iterable[str]) -> None:
    """``ValueError`` if ``na_ignore_case`` is set without any non-blank ``na_tokens``."""
    if na_ignore_case and not any(token.strip() for token in na_tokens):
        raise ValueError("na_ignore_case needs na_tokens (the missing-value texts to match)")


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """``pattern`` compiled; ``ValueError`` if it is empty or not a valid regular expression."""
    if not pattern:
        raise ValueError("a pattern must not be empty")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid regular expression {pattern!r}: {exc}") from None


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
    skipped_lines: int = 0  # --skip-lines: lines skipped before the header
    skipped_footer: int = 0  # --skip-footer: records dropped after the data
    number_affixes: tuple[str, ...] = ()  # --number-affix texts, as validated
    accounting_negatives: bool = False  # (1.234,56) and 1.234,56- were read as negative
    month_names: bool = False  # --month-names: dates such as 05-oct-2026 were read
    # All column names of the file, after duplicate-name suffixes; ``columns``
    # holds only the selected ones when ``selected_columns`` is set.
    header: tuple[str, ...] = ()
    selected_columns: tuple[str, ...] | None = None  # --columns, in the order given
    keys: tuple[KeyProfile, ...] = ()  # --unique-key: one per key whose columns all exist
    domains: tuple[DomainProfile, ...] = ()  # --allowed-values: one per profiled column
    patterns: tuple[PatternProfile, ...] = ()  # --pattern: one per profiled column
    na_ignore_case: bool = False  # --na-ignore-case: na_tokens were matched in any case


def _untrimmed_names(header: list[str]) -> tuple[str, ...]:
    """Header names, as reported, that have leading or trailing whitespace."""
    return tuple(name for name in header if name != name.strip())


def _row_digest(row: Sequence[str]) -> bytes:
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
    month_names: bool = False  # only with date_order

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
    month_names: bool = False,
) -> _Rules:
    """Validate the reading options; ``ValueError`` when unsupported or contradictory."""
    check_thousands(thousands, decimal_comma)
    check_date_order(date_order)
    check_month_names(month_names, date_order)
    return _Rules(
        decimal_comma=decimal_comma,
        thousands=thousands,
        date_order=date_order,
        bool_map=bool_word_map(bool_words) if bool_words else None,
        # Longer affixes first: when two would both leave a number, the longer wins.
        affixes=tuple(sorted(check_number_affixes(number_affixes), key=len, reverse=True)),
        accounting=accounting_negatives,
        month_names=month_names,
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
        plain = [normalize_date(v, rules.date_order, rules.month_names) for v in plain]
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


def _fold_missing(value: str) -> str:
    """Compare opt-in missing markers under Unicode case and NFC equivalence.

    Both the configured tokens and CSV cells use the same normalization.
    Values retained in reports and unique-key fingerprints remain unmodified.
    """
    return normalize("NFC", value.casefold())


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

    def strip_counts(self, na: set[str], fold: bool = False) -> None:
        """Turn raw cell-text counts into stripped-value counts.

        The pass counts cells exactly as read; this merges them by stripped
        text once per distinct value, counting as ``untrimmed`` the non-missing
        cells that had surrounding whitespace, then moves missing cells (empty
        or in ``na``) out of the counter. First-seen order, which decides ties
        in top values, is kept: each stripped value takes the position of its
        first raw spelling.

        With ``fold`` (``--na-ignore-case``), ``na`` holds case-folded tokens
        and a value is missing when its case-folded NFC form is one of them.
        """
        raw = self.counts
        if any(key != key.strip() for key in raw):
            merged: Counter[str] = Counter()
            for key, count in raw.items():
                value = key.strip()
                merged[value] += count
                if value != key and (_fold_missing(value) if fold else value) not in na:
                    self.untrimmed += count
            self.counts = merged
        if fold:
            tokens = [value for value in self.counts if _fold_missing(value) in na]
            self.missing = sum(self.counts.pop(token) for token in tokens)
        else:
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


class _KeyAccumulator:
    """Uniqueness of one composite key, updated batch by batch.

    Each checked row adds one 128-bit fingerprint of its stripped key cells
    (lengths first, as for duplicate rows), so memory grows with the number of
    distinct keys, not with the size of the values. The texts of the first
    ``limit`` repeated keys are kept, since a fingerprint cannot be read back.
    """

    __slots__ = ("columns", "examples", "limit", "positions", "repeated", "seen", "skipped")

    def __init__(self, columns: tuple[str, ...], positions: list[int], limit: int) -> None:
        self.columns = columns
        self.positions = positions
        self.limit = limit
        self.seen: set[bytes] = set()
        self.skipped = 0
        self.repeated = 0
        self.examples: dict[bytes, list[Any]] = {}  # fingerprint -> [key, rows]

    def update(self, batch: list[list[str]], na: set[str], fold: bool = False) -> None:
        # Hashing the keys is most of the cost; a C-level fast path for
        # batches without repeats measured within 5% of this loop.
        cells = [[row[position].strip() for row in batch] for position in self.positions]
        if fold:  # --na-ignore-case: ``na`` holds case-folded tokens
            keys = [
                key
                for key in zip(*cells, strict=True)
                if na.isdisjoint([_fold_missing(cell) for cell in key])
            ]
        else:
            keys = [key for key in zip(*cells, strict=True) if na.isdisjoint(key)]
        self.skipped += len(batch) - len(keys)
        seen, examples = self.seen, self.examples
        for key in keys:
            digest = _row_digest(key)
            if digest not in seen:
                seen.add(digest)
                continue
            self.repeated += 1
            example = examples.get(digest)
            if example is not None:
                example[1] += 1
            elif len(examples) < self.limit:
                examples[digest] = [key, 2]

    def finish(self, total: int) -> KeyProfile:
        examples = sorted(self.examples.values(), key=lambda item: -item[1])  # stable
        return KeyProfile(
            columns=self.columns,
            checked=total - self.skipped,
            skipped=self.skipped,
            repeated=self.repeated,
            examples=tuple((tuple(key), rows) for key, rows in examples),
        )


def key_columns(names: Iterable[str]) -> tuple[str, ...]:
    """The columns of a composite key, repeated names once; ``ValueError`` when empty.

    A key is a sequence of names: one string would be read letter by letter,
    so it raises ``ValueError`` too.
    """
    if isinstance(names, str):
        raise ValueError(f"a unique key is a sequence of column names, not a string: {names!r}")
    columns = tuple(dict.fromkeys(names))
    if not columns:
        raise ValueError("a unique key needs at least one column")
    return columns


def _key_accumulators(
    header: list[str], unique_keys: Iterable[Iterable[str]], limit: int
) -> list[_KeyAccumulator]:
    """One accumulator per distinct key whose columns are all in ``header``.

    Keys naming an unknown column are left out here: ``evaluate`` reports
    those names as missing required columns.
    """
    position = {name: i for i, name in enumerate(header)}
    keys = dict.fromkeys(key_columns(key) for key in unique_keys)
    return [
        _KeyAccumulator(key, [position[name] for name in key], limit)
        for key in keys
        if all(name in position for name in key)
    ]


@dataclass(frozen=True)
class _Profiled:
    columns: list[ColumnProfile]
    rows: int
    duplicate_rows: int
    keys: tuple[KeyProfile, ...] = ()
    domains: tuple[DomainProfile, ...] = ()
    patterns: tuple[PatternProfile, ...] = ()


def _columns(
    batch: list[list[str]],
    selected: list[int] | None,
    pick: Callable[[list[str]], tuple[str, ...]] | None,
) -> Iterable[Sequence[str]]:
    """The cells of ``batch`` column by column: every column, or the ``selected`` ones."""
    if selected is None:
        return zip(*batch, strict=True)
    if pick is None:  # a single selected column: itemgetter would return bare values
        return [[row[selected[0]] for row in batch]]
    return zip(*map(pick, batch), strict=True)


_MAX_LISTED = 10  # header names listed in a column selection error


def _selection(header: list[str], columns: Sequence[str] | None) -> list[int] | None:
    """Positions of the selected ``columns`` in ``header``, in the order given.

    ``None`` selects every column. Repeated names count once. A name that is
    not in the header raises ``ColumnSelectionError``, which names the header
    columns and a column that only differs by surrounding whitespace.
    """
    if columns is None:
        return None
    names = list(dict.fromkeys(columns))
    if not names:
        raise ColumnSelectionError("no columns selected")
    position = {name: i for i, name in enumerate(header)}
    missing = [name for name in names if name not in position]
    if missing:
        quoted = ", ".join(f"'{name}'" for name in missing)
        noun = "column" if len(missing) == 1 else "columns"
        verb = "is" if len(missing) == 1 else "are"
        listed = ", ".join(header[:_MAX_LISTED]) + (", ..." if len(header) > _MAX_LISTED else "")
        message = f"selected {noun} {quoted} {verb} not in the header (columns: {listed})"
        near = [h for h in header if h.strip() in {name.strip() for name in missing}]
        raise ColumnSelectionError(message + (f"; did you mean '{near[0]}'?" if near else ""))
    return [position[name] for name in names]


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
    columns: Sequence[str] | None = None,
    unique_keys: Iterable[Iterable[str]] = (),
    allowed_values: Mapping[str, Iterable[str]] | None = None,
    patterns: Mapping[str, str] | None = None,
    month_names: bool = False,
    na_ignore_case: bool = False,
) -> _Profiled:
    """Profile ``rows`` in a single pass; each row must have ``len(header)`` cells.

    Cells whose stripped text is one of ``na_tokens`` count as missing, like
    empty cells. They are removed from the counters once, after the pass, so
    they cost nothing per row.

    ``duplicate_rows`` counts rows that exactly repeat an earlier row. Rows are
    compared by a 128-bit BLAKE2b fingerprint of their cell texts instead of
    being stored, so a false match would need a hash collision (probability
    below 1e-20 even for billions of rows).

    ``thousands``, ``date_order``, ``bool_words``, ``number_affixes`` and
    ``month_names`` are validated before any row is read and raise
    ``ValueError`` when unsupported or contradictory (``month_names`` needs a
    ``date_order``).

    ``columns`` limits the profile to those header names, in that order; a
    name that is not in the header raises ``ColumnSelectionError`` before any
    row is read. Duplicate rows still compare whole rows.

    ``unique_keys`` are composite keys, each a sequence of column names, whose
    uniqueness is measured in the same pass (see ``KeyProfile``). Rows are
    read whole, so a key may use columns that ``columns`` leaves out. A key
    with an unknown name is skipped (``evaluate`` reports it); an empty key
    raises ``ValueError``. Without keys the pass does no extra work.

    ``allowed_values`` maps column names to the values their non-missing
    cells may hold (see ``DomainProfile``). It is checked after the pass,
    once per distinct value, so it costs neither a pass nor memory. A name
    that is not profiled is skipped (``evaluate`` reports it); an empty list
    or value raises ``ValueError`` before any row is read.

    ``patterns`` maps column names to regular expressions their non-missing
    values must match as a whole (see ``PatternProfile``). Like
    ``allowed_values``, each distinct value is matched once after the pass;
    a name that is not profiled is skipped, and an empty or invalid pattern
    raises ``ValueError`` before any row is read.

    ``na_ignore_case`` matches ``na_tokens`` after Unicode case folding and NFC,
    so ``S/D`` and ``s/d`` are both missing for the token ``s/d``; without
    ``na_tokens`` it raises ``ValueError`` before any row is read.
    """
    if top_n < 0:
        raise ValueError("top_n must be 0 or greater")
    # Materialize one-shot iterables before validation and missing-cell accounting.
    na_tokens = tuple(na_tokens)
    check_na_ignore_case(na_ignore_case, na_tokens)
    rules = _reading_rules(
        decimal_comma,
        thousands,
        date_order,
        bool_words,
        number_affixes,
        accounting_negatives,
        month_names,
    )
    domains = {name: allowed_list(values) for name, values in (allowed_values or {}).items()}
    formats = {name: compile_pattern(pattern) for name, pattern in (patterns or {}).items()}
    selected = _selection(header, columns)
    accumulators = [
        _ColumnAccumulator(name)
        for name in (header if selected is None else [header[i] for i in selected])
    ]
    counters = [acc.counts for acc in accumulators]
    # Selected cells of each row, as a tuple (itemgetter returns a bare value
    # for one position, hence the one-element case).
    pick = None if selected is None or len(selected) < 2 else itemgetter(*selected)
    seen: set[bytes] = set()
    na = {token.strip() for token in na_tokens} | {""}
    if na_ignore_case:
        na = {_fold_missing(token) for token in na}
    keys = _key_accumulators(header, unique_keys, top_n)
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
        for key in keys:
            key.update(batch, na, na_ignore_case)
        # The transposed batch is built inside the loop header, so nothing keeps
        # it alive while the next batch is read (one batch in memory at a time).
        for counter, column in zip(counters, _columns(batch, selected, pick), strict=True):
            counter.update(column)
    for acc in accumulators:
        acc.strip_counts(na, na_ignore_case)
    return _Profiled(
        columns=[acc.finish(total, top_n, rules) for acc in accumulators],
        rows=total,
        duplicate_rows=total - len(seen),
        keys=tuple(key.finish(total) for key in keys),
        domains=tuple(
            _domain(acc, domains[acc.name], top_n) for acc in accumulators if acc.name in domains
        ),
        patterns=tuple(
            _pattern(acc, formats[acc.name], top_n) for acc in accumulators if acc.name in formats
        ),
    )


def _domain(acc: _ColumnAccumulator, allowed: tuple[str, ...], top_n: int) -> DomainProfile:
    """The cells of ``acc`` (stripped, without missing ones) whose value is not ``allowed``."""
    permitted = set(allowed)
    unexpected, examples = _outside(acc.counts, permitted.__contains__, top_n)
    return DomainProfile(column=acc.name, allowed=allowed, unexpected=unexpected, examples=examples)


def _pattern(acc: _ColumnAccumulator, pattern: re.Pattern[str], top_n: int) -> PatternProfile:
    """The cells of ``acc`` (stripped, without missing ones) whose value does not match."""
    mismatched, examples = _outside(acc.counts, pattern.fullmatch, top_n)
    return PatternProfile(
        column=acc.name, pattern=pattern.pattern, mismatched=mismatched, examples=examples
    )


def _outside(
    counts: Counter[str], accepts: Callable[[str], object], top_n: int
) -> tuple[int, tuple[tuple[str, int], ...]]:
    """The cells of ``counts`` whose value ``accepts`` rejects (returns a falsy result for).

    Returns their exact number and the ``top_n`` most frequent of their values
    with their cells, first seen on ties (``Counter.most_common`` order). Each
    distinct value is tested once, and the rejected values are streamed into
    ``heapq.nlargest`` instead of being copied, so a column whose values are
    all rejected needs no second copy of its counts.
    """
    cells = 0

    def rejected() -> Iterator[tuple[str, int]]:
        nonlocal cells
        for value, count in counts.items():
            if not accepts(value):
                cells += count
                yield value, count

    values = rejected()
    # nlargest is documented as sorted(..., reverse=True)[:n], stable on ties
    # like most_common; with n == 0 it reads nothing, hence the drain after it.
    examples = tuple(heapq.nlargest(top_n, values, key=itemgetter(1)))
    deque(values, maxlen=0)
    return cells, examples


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
    columns: Sequence[str] | None,
    month_names: bool = False,
    na_ignore_case: bool = False,
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
        skipped_lines=source.skipped_lines,
        skipped_footer=source.skipped_footer,
        thousands=thousands,
        date_order=date_order,
        bool_words=bool_words,
        number_affixes=check_number_affixes(number_affixes),
        accounting_negatives=accounting_negatives,
        month_names=month_names,
        header=tuple(source.header),
        selected_columns=None if columns is None else tuple(dict.fromkeys(columns)),
        keys=result.keys,
        domains=result.domains,
        patterns=result.patterns,
        na_ignore_case=na_ignore_case,
    )


def build_report(
    table: Table,
    decimal_comma: bool = False,
    na_tokens: Iterable[str] = (),
    top_n: int = TOP_N,
    thousands: str | None = None,
    date_order: str | None = None,
    bool_words: BoolWords = (),
    number_affixes: tuple[str, ...] = (),
    accounting_negatives: bool = False,
    columns: Sequence[str] | None = None,
    unique_keys: Iterable[Iterable[str]] = (),
    allowed_values: Mapping[str, Iterable[str]] | None = None,
    patterns: Mapping[str, str] | None = None,
    month_names: bool = False,
    na_ignore_case: bool = False,
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
    and ``1.234,56-`` as negative numbers; ``columns`` profiles only those
    header names, in that order; ``unique_keys`` are composite keys whose
    uniqueness is measured (``Report.keys``); ``allowed_values`` maps column
    names to the values they may hold (``Report.domains``); ``patterns``
    maps column names to regular expressions their values must match
    (``Report.patterns``); ``month_names``, with a ``date_order``, also reads
    Spanish or English month names such as ``05-oct-2026``; ``na_ignore_case``
    matches ``na_tokens`` after case folding and NFC (``Report.na_ignore_case``).
    """
    tokens = tuple(na_tokens)
    result = profile_rows(
        table.header,
        table.rows,
        decimal_comma,
        tokens,
        top_n,
        thousands,
        date_order,
        bool_words,
        number_affixes,
        accounting_negatives,
        columns,
        unique_keys,
        allowed_values,
        patterns,
        month_names,
        na_ignore_case,
    )
    return _report(
        result,
        table,
        tokens,
        top_n,
        thousands,
        date_order,
        bool_words,
        number_affixes,
        accounting_negatives,
        columns,
        month_names,
        na_ignore_case,
    )


def profile_file(
    path: PathArg,
    max_rows: int | None = None,
    delimiter: str = ",",
    decimal_comma: bool = False,
    na_tokens: Iterable[str] = (),
    top_n: int = TOP_N,
    encoding: str = DEFAULT_ENCODING,
    max_field_size: int | None = None,
    thousands: str | None = None,
    date_order: str | None = None,
    bool_words: BoolWords = (),
    number_affixes: tuple[str, ...] = (),
    accounting_negatives: bool = False,
    columns: Sequence[str] | None = None,
    unique_keys: Iterable[Iterable[str]] = (),
    allowed_values: Mapping[str, Iterable[str]] | None = None,
    patterns: Mapping[str, str] | None = None,
    skip_lines: int = 0,
    skip_footer: int = 0,
    month_names: bool = False,
    na_ignore_case: bool = False,
) -> Report:
    """Stream ``path`` and profile it without loading the whole file into memory.

    ``path`` is a ``str`` or any path-like object; ``"-"`` reads standard input.

    Same rules and errors as ``reader.open_rows``; same result as
    ``build_report(read_table(...))``. ``skip_lines`` lines before the header
    are skipped (``Report.skipped_lines``), and ``skip_footer`` records after
    the data are dropped (``Report.skipped_footer``). ``month_names`` and
    ``na_ignore_case`` are as in ``build_report``.
    """
    if top_n < 0:
        raise ValueError("top_n must be 0 or greater")
    tokens = tuple(na_tokens)
    with open_rows(
        path,
        max_rows=max_rows,
        delimiter=delimiter,
        encoding=encoding,
        max_field_size=max_field_size,
        skip_lines=skip_lines,
        skip_footer=skip_footer,
    ) as stream:
        result = profile_rows(
            stream.header,
            stream,
            decimal_comma,
            tokens,
            top_n,
            thousands,
            date_order,
            bool_words,
            number_affixes,
            accounting_negatives,
            columns,
            unique_keys,
            allowed_values,
            patterns,
            month_names,
            na_ignore_case,
        )
        return _report(
            result,
            stream,
            tokens,
            top_n,
            thousands,
            date_order,
            bool_words,
            number_affixes,
            accounting_negatives,
            columns,
            month_names,
            na_ignore_case,
        )
