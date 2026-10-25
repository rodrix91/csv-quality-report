"""Command-line entry point."""

from __future__ import annotations

import argparse
import io
import math
import os
import re
import sys
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

from . import __version__
from .checks import (
    COLUMN_TYPES,
    Bound,
    TypeChangeRule,
    ValueRange,
    baseline_age_check,
    evaluate,
    missing_increase_checks,
    range_bounds_problem,
    row_drop_check,
    schema_change_check,
)
from .clock import current_time, format_stamp
from .compare import compare_reports, load_baseline
from .errors import EXIT_CHECKS, CsvQualityError, OutputWriteError
from .inference import (
    DATE_ORDERS,
    bool_word_map,
    check_number_affixes,
    check_thousands,
    parse_datetime,
)
from .output import write_atomic
from .profile import TOP_N, allowed_list, compile_pattern, profile_file
from .reader import (
    DEFAULT_ENCODING,
    DELIMITER_AUTO,
    PathArg,
    display_name,
    is_stdin,
    normalize_encoding,
)
from .render import render_json, render_markdown


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


_DELIMITER_ALIASES = {"tab": "\t", "\\t": "\t", "comma": ",", "semicolon": ";", "pipe": "|"}


def _delimiter(text: str) -> str:
    """Accept one character, ``auto``, or an alias such as ``tab`` or ``semicolon``."""
    if text.lower() == DELIMITER_AUTO:
        return DELIMITER_AUTO
    value = _DELIMITER_ALIASES.get(text.lower(), text)
    if len(value) != 1:
        raise argparse.ArgumentTypeError(
            f"invalid delimiter: {text!r} (use one character, auto, or tab/comma/semicolon/pipe)"
        )
    if value in {'"', "\r", "\n"}:
        raise argparse.ArgumentTypeError(f"invalid delimiter: {text!r} (reserved character)")
    return value


def _na_tokens(text: str) -> tuple[str, ...]:
    """Parse ``NA,null,-`` into unique, stripped, non-empty tokens (order kept)."""
    tokens = tuple(dict.fromkeys(t.strip() for t in text.split(",") if t.strip()))
    if not tokens:
        raise argparse.ArgumentTypeError(f"invalid --na value: {text!r} (no tokens)")
    return tokens


def _percentage(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid percentage: {text!r}") from None
    if not 0.0 <= value <= 100.0:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return value


_DURATION = re.compile(r"([0-9]+)([smhdw])")
_DURATION_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _duration(text: str, option: str = "--max-baseline-age", shown: str | None = None) -> int:
    """Parse a duration such as ``36h`` or ``7d`` into seconds (a positive whole number)."""
    match = _DURATION.fullmatch(text.strip())
    if match is None or int(match[1]) == 0:
        raise argparse.ArgumentTypeError(
            f"invalid {option} value: {text if shown is None else shown!r} (use a positive "
            "whole number with s, m, h, d or w, such as 36h or 7d)"
        )
    return int(match[1]) * _DURATION_SECONDS[match[2]]


def _column_allowed(text: str) -> tuple[str, tuple[str, ...]]:
    """Parse ``NAME=V1,V2`` for --allowed-values (split at the last ``=``, values at commas)."""
    name, sep, values = text.rpartition("=")
    usage = f"invalid --allowed-values value: {text!r} (use NAME=VALUE,VALUE, such as "
    if not sep or not name:
        raise argparse.ArgumentTypeError(usage + "Moneda=PYG,USD)")
    try:
        return name, allowed_list(values.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(
            usage + "Moneda=PYG,USD; every value must be non-empty)"
        ) from None


def _column_pattern(text: str) -> tuple[str, str]:
    """Split at the first unescaped '='; headers may spell literal '=' as '\\='."""
    parts = re.split(r"(?<!\\)=", text, maxsplit=1)
    name, pattern = parts if len(parts) == 2 else ("", "")
    name = name.replace(r"\=", "=")
    if not name or not pattern:
        raise argparse.ArgumentTypeError(
            f"invalid --pattern value: {text!r} (use NAME=REGEX, such as CP=[0-9]{{4}})"
        )
    try:
        compile_pattern(pattern)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid --pattern value for {name!r}: {exc}") from None
    return name, pattern


def _column_age(text: str) -> tuple[str, int]:
    """Parse ``NAME=DURATION`` for --max-age (split at the last ``=``)."""
    name, sep, value = text.rpartition("=")
    if not sep or not name:
        raise argparse.ArgumentTypeError(
            f"invalid --max-age value: {text!r} (use NAME=DURATION, such as Despacho=2d)"
        )
    return name, _duration(value, "--max-age", text)


_UTC_OFFSET = re.compile(r"([+-])([0-9]{2}):([0-9]{2})")


def _utc_offset(text: str) -> timedelta:
    """Parse ``Z`` or ``±HH:MM`` (up to 14:00, minutes below 60) into a ``timedelta``."""
    if text.strip() in ("Z", "z"):
        return timedelta(0)
    match = _UTC_OFFSET.fullmatch(text.strip())
    if match is None or int(match[3]) >= 60 or (int(match[2]), int(match[3])) > (14, 0):
        raise argparse.ArgumentTypeError(
            f"invalid --utc-offset value: {text!r} (use Z or +HH:MM / -HH:MM, such as -04:00)"
        )
    offset = timedelta(hours=int(match[2]), minutes=int(match[3]))
    return -offset if match[1] == "-" else offset


def _non_negative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return value


def _column_limit(text: str, option: str = "--max-missing-column") -> tuple[str, float]:
    """Parse ``NAME=PCT``; the last ``=`` separates them, so names may contain ``=``."""
    name, sep, value = text.rpartition("=")
    if not sep or not name:
        raise argparse.ArgumentTypeError(f"invalid {option} value: {text!r} (use NAME=PCT)")
    return name, _percentage(value)


def _encoding(text: str) -> str:
    try:
        return normalize_encoding(text)
    except LookupError as exc:
        raise argparse.ArgumentTypeError(f"invalid --encoding value: {text!r} ({exc})") from None


_THOUSANDS_ALIASES = {".": ".", "dot": ".", ",": ",", "comma": ",", " ": " ", "space": " "}


def _thousands(text: str) -> str:
    value = _THOUSANDS_ALIASES.get(text.lower())
    if value is None:
        raise argparse.ArgumentTypeError(
            f"invalid --thousands value: {text!r} (use dot, comma or space)"
        )
    return value


def _bool_words(text: str) -> tuple[str, str]:
    """Parse ``sí,no`` into a (true word, false word) pair of stripped words."""
    words = [word.strip() for word in text.split(",")]
    if len(words) != 2 or not all(words):
        raise argparse.ArgumentTypeError(
            f"invalid --bool-words value: {text!r} (use TRUE,FALSE, e.g. sí,no)"
        )
    return words[0], words[1]


def _column_affixes(text: str) -> tuple[str, int]:
    """Parse ``NAME=N``; the last ``=`` separates them, so names may contain ``=``."""
    name, sep, value = text.rpartition("=")
    if not sep or not name:
        raise argparse.ArgumentTypeError(f"invalid --max-affixes value: {text!r} (use NAME=N)")
    try:
        return name, _non_negative_int(value)
    except argparse.ArgumentTypeError as exc:
        raise argparse.ArgumentTypeError(f"invalid --max-affixes value: {text!r} ({exc})") from None


_ISO_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# The shape of an ISO 8601 date-time bound: date, time and an optional offset.
# Loose on purpose (any calendar values, any number of fraction digits), so
# _bound() can say why a value that looks like a date-time is not a valid one.
_ISO_DATETIME = (
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?"
    r"(?:Z|[+-][0-9]{2}(?::?[0-9]{2})?)?"
)
_ISO_DATETIME_RE = re.compile(_ISO_DATETIME)
# MIN:MAX, where a side is empty, a date-time (which contains colons) or any
# text without a colon. Date-times are tried first, so the colon that splits
# the range is the one between two bounds: 2026-10-01T08:00:2026-10-01T18:00.
_RANGE_SPEC_RE = re.compile(rf"\s*({_ISO_DATETIME}|[^:]*?)\s*:\s*({_ISO_DATETIME}|[^:]*?)\s*")


def _bound(text: str, option: str) -> Bound:
    """One side of a ``--range``: empty (open), an ISO date or date-time, or a finite number."""
    if not text:
        return None
    if _ISO_DATE_RE.fullmatch(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"invalid --range value: {option!r} ({text!r} is not a valid date)"
            ) from None
    if _ISO_DATETIME_RE.fullmatch(text):
        moment = parse_datetime(text)
        if moment is None:
            raise argparse.ArgumentTypeError(
                f"invalid --range value: {option!r} ({text!r} is not a valid date-time)"
            )
        return moment
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid --range value: {option!r} ({text!r} is not a number, "
            "a YYYY-MM-DD date or an ISO 8601 date-time)"
        ) from None
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError(
            f"invalid --range value: {option!r} ({text!r} is not a finite number)"
        )
    return number


def _column_range(text: str) -> tuple[str, ValueRange]:
    """Parse ``NAME=MIN:MAX``; either bound may be empty, names may contain ``=``."""
    name, sep, spec = text.rpartition("=")
    match = _RANGE_SPEC_RE.fullmatch(spec)
    # A lone date-time would split inside its time (2026-10-01T08 and 00).
    if not sep or not name or match is None or _ISO_DATETIME_RE.fullmatch(spec.strip()):
        raise argparse.ArgumentTypeError(
            f"invalid --range value: {text!r} (use NAME=MIN:MAX; one side may be empty)"
        )
    low, high = _bound(match[1], text), _bound(match[2], text)
    if low is None and high is None:
        raise argparse.ArgumentTypeError(f"invalid --range value: {text!r} (give MIN, MAX or both)")
    problem = range_bounds_problem(low, high)
    if problem:
        raise argparse.ArgumentTypeError(f"invalid --range value: {text!r} ({problem})")
    if low is not None and high is not None and low > high:  # type: ignore[operator]
        raise argparse.ArgumentTypeError(
            f"invalid --range value: {text!r} (MIN is greater than MAX)"
        )
    return name, (low, high)


def _column_type(text: str) -> tuple[str, str]:
    """Parse ``NAME=TYPE``; the last ``=`` separates them, so names may contain ``=``."""
    name, sep, kind = text.rpartition("=")
    if not sep or not name:
        raise argparse.ArgumentTypeError(f"invalid --require-type value: {text!r} (use NAME=TYPE)")
    if kind not in COLUMN_TYPES:
        raise argparse.ArgumentTypeError(
            f"invalid type in --require-type: {kind!r} (use one of {', '.join(COLUMN_TYPES)})"
        )
    return name, kind


def _type_change_rule(text: str) -> TypeChangeRule:
    """Parse ``FROM:TO`` (any column) or ``NAME=FROM:TO``; names may contain ``=``."""
    name, sep, spec = text.rpartition("=")
    kinds = spec.split(":")
    if (sep and not name) or len(kinds) != 2:
        raise argparse.ArgumentTypeError(
            f"invalid --allow-type-change value: {text!r} (use FROM:TO or NAME=FROM:TO)"
        )
    try:
        return TypeChangeRule(kinds[0], kinds[1], name if sep else None)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid --allow-type-change value: {text!r} ({exc})"
        ) from None


def _column_names(text: str, option: str = "--require-columns") -> tuple[str, ...]:
    """Parse ``id,date,weight`` into unique, stripped, non-empty names (order kept)."""
    names = tuple(dict.fromkeys(n.strip() for n in text.split(",") if n.strip()))
    if not names:
        raise argparse.ArgumentTypeError(f"invalid {option} value: {text!r} (no names)")
    return names


def _selected_column_names(text: str) -> tuple[str, ...]:
    """Require a name in every selected-column position."""
    if text.strip() and any(not part.strip() for part in text.split(",")):
        raise argparse.ArgumentTypeError(
            f"invalid --columns value: {text!r} (empty column; specify every selected column)"
        )
    return _column_names(text, "--columns")


def _required_column_names(text: str) -> tuple[str, ...]:
    """Reject omitted required-column positions rather than silently skipping a gate."""
    if not text.strip():
        return _column_names(text)
    if any(not part.strip() for part in text.split(",")):
        raise argparse.ArgumentTypeError(
            f"invalid --require-columns value: {text!r} "
            "(empty column; specify every required column)"
        )
    return _column_names(text)


def _column_name(text: str, option: str = "--unique") -> str:
    """One column name, exactly as written (commas and ``=`` are part of it)."""
    if not text.strip():
        raise argparse.ArgumentTypeError(f"invalid {option} value: {text!r} (no name)")
    return text


def _key_names(text: str) -> tuple[str, ...]:
    """Reject omitted composite-key columns before checking their uniqueness."""
    names = _column_names(text, "--unique-key")
    if any(not part.strip() for part in text.split(",")):
        raise argparse.ArgumentTypeError(
            f"invalid --unique-key value: {text!r} (empty column; specify every key column)"
        )
    return names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m csv_quality_report",
        description="Quick data-quality report for a CSV file.",
    )
    parser.add_argument(
        "path",
        # Kept as typed, not as a Path, so reports and messages name the file
        # the same way on every platform (#120).
        type=str,
        help="CSV file to analyze (UTF-8 unless --encoding; gzip is detected); - reads stdin",
    )
    parser.add_argument("--version", action="version", version=f"csv-quality-report {__version__}")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="output format (default: markdown)",
    )
    parser.add_argument(
        "--max-rows",
        type=_positive_int,
        default=None,
        metavar="N",
        help="analyze only the first N data rows",
    )
    parser.add_argument(
        "--delimiter",
        type=_delimiter,
        default=",",
        metavar="CHAR",
        help="field separator: one character, auto (detect among , ; tab |), "
        "or tab/comma/semicolon/pipe (default: ,)",
    )
    parser.add_argument(
        "--skip-lines",
        type=_non_negative_int,
        default=0,
        metavar="N",
        help="skip the first N lines (title lines before the header; a sep= line is not counted)",
    )
    parser.add_argument(
        "--skip-footer",
        type=_non_negative_int,
        default=0,
        metavar="N",
        help="drop the last N records (a footer after the data: totals rows, a record count; "
        "blank lines are not counted)",
    )
    parser.add_argument(
        "--decimal-comma",
        action="store_true",
        help="numbers use ',' as decimal mark (10,5); values written with '.' are not floats",
    )
    parser.add_argument(
        "--thousands",
        type=_thousands,
        default=None,
        metavar="SEP",
        help="thousands separator in numbers: dot (needs --decimal-comma), comma or space",
    )
    parser.add_argument(
        "--date-order",
        choices=DATE_ORDERS,
        default=None,
        help="read dates such as 05/10/2026 (/ - or . separators, 4-digit years, optional "
        "time) as day/month/year (dmy), month/day/year (mdy) or year/month/day (ymd); "
        "never guessed",
    )
    parser.add_argument(
        "--bool-words",
        type=_bool_words,
        action="append",
        default=[],
        metavar="TRUE,FALSE",
        help="also read these words as booleans, any case, e.g. sí,no or verdadero,falso "
        "(repeatable; true/false always count)",
    )
    parser.add_argument(
        "--number-affix",
        action="append",
        default=[],
        metavar="TEXT",
        help="text allowed before or after numbers, such as $, Gs., kg or %% (repeatable; "
        "removed only when the rest is a number; each column reports which it had)",
    )
    parser.add_argument(
        "--accounting-negatives",
        action="store_true",
        help="read (1.234,56) and 1.234,56- (trailing minus, as SAP writes it) as negative numbers",
    )
    parser.add_argument(
        "--na",
        type=_na_tokens,
        default=(),
        metavar="TOKENS",
        help="comma-separated cell values to count as missing, e.g. NA,null,- (case-sensitive)",
    )
    parser.add_argument(
        "--top",
        type=_non_negative_int,
        default=TOP_N,
        metavar="N",
        help=f"how many most frequent values to list per column (default: {TOP_N}; 0: none)",
    )
    parser.add_argument(
        "--encoding",
        type=_encoding,
        default=DEFAULT_ENCODING,
        metavar="NAME",
        help="text encoding of the file, e.g. cp1252, latin-1, utf-16 (default: utf-8)",
    )
    parser.add_argument(
        "--max-field-size",
        type=_positive_int,
        default=None,
        metavar="N",
        help="allow CSV fields up to N characters (Python's default limit is 131072)",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        metavar="FILE",
        help="also write the JSON report (with checks) to FILE; stdout keeps --format",
    )
    parser.add_argument(
        "--record-time",
        action="store_true",
        help='add the UTC time the run started ("generated_at") to the JSON report, so a '
        "later run can check its age with --max-baseline-age (SOURCE_DATE_EPOCH, when set, "
        "replaces the clock)",
    )
    gates = parser.add_argument_group(
        "quality gates", f"exit with code {EXIT_CHECKS} when a threshold is exceeded"
    )
    gates.add_argument(
        "--max-missing",
        type=_percentage,
        default=None,
        metavar="PCT",
        help="fail if any column has more than PCT %% missing values (0-100)",
    )
    gates.add_argument(
        "--max-missing-column",
        type=_column_limit,
        action="append",
        default=[],
        metavar="NAME=PCT",
        help="per-column missing limit, overrides --max-missing for NAME (repeatable)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        metavar="REPORT",
        help="compare with an earlier JSON report of the same source (from --format json or "
        "--json-output): added, removed and retyped columns, missing-value and row changes",
    )
    parser.add_argument(
        "--check-baseline-missing-rate",
        action="store_true",
        help=(
            "with --baseline: reject a historical 'missing_pct' that contradicts "
            "its exact 'missing' count beyond one-decimal rounding"
        ),
    )
    parser.add_argument(
        "--columns",
        type=_selected_column_names,
        default=None,
        metavar="NAMES",
        help="profile only these comma-separated columns, in this order (rows are still read "
        "whole: duplicates compare full rows, --require-columns checks the full header)",
    )
    gates.add_argument(
        "--require-columns",
        type=_required_column_names,
        default=(),
        metavar="NAMES",
        help="fail if any of these comma-separated columns is missing (exact, case-sensitive)",
    )
    gates.add_argument(
        "--require-type",
        type=_column_type,
        action="append",
        default=[],
        metavar="NAME=TYPE",
        help="fail unless column NAME has TYPE (int, float, bool, date, datetime, string); "
        "repeatable",
    )
    gates.add_argument(
        "--max-affixes",
        type=_column_affixes,
        action="append",
        default=[],
        metavar="NAME=N",
        help="fail if column NAME mixes more than N distinct --number-affix texts, such as "
        "two currencies or units; NAME=1 allows one (repeatable)",
    )
    gates.add_argument(
        "--range",
        type=_column_range,
        action="append",
        default=[],
        metavar="NAME=MIN:MAX",
        help="fail if column NAME has values outside MIN..MAX (inclusive; numbers, "
        "YYYY-MM-DD dates for date or datetime columns, or ISO 8601 date-times; one side "
        "may be empty); repeatable",
    )
    gates.add_argument(
        "--unique",
        type=_column_name,
        action="append",
        default=[],
        metavar="NAME",
        help="fail if column NAME has a non-missing value more than once, such as a "
        "repeated invoice number (stripped text, case-sensitive); repeatable",
    )
    gates.add_argument(
        "--unique-key",
        type=_key_names,
        action="append",
        default=[],
        metavar="NAMES",
        help="fail if two rows share the values of all the comma-separated columns NAMES, "
        "such as invoice number and line (stripped text, case-sensitive; rows with a "
        "missing key cell are skipped); repeatable",
    )
    gates.add_argument(
        "--allowed-values",
        type=_column_allowed,
        action="append",
        default=[],
        metavar="NAME=VALUES",
        help="fail if a non-missing cell of column NAME holds a value outside the "
        "comma-separated VALUES, such as Moneda=PYG,USD (stripped text, case-sensitive); "
        "repeatable",
    )
    gates.add_argument(
        "--pattern",
        type=_column_pattern,
        action="append",
        default=[],
        metavar="NAME=REGEX",
        help="fail if a non-missing cell of column NAME does not match the regular "
        "expression REGEX as a whole, such as CP=[0-9]{4} (stripped text, Python re "
        "syntax; NAME ends at the first =); repeatable",
    )
    gates.add_argument(
        "--max-age",
        type=_column_age,
        action="append",
        default=[],
        metavar="NAME=DURATION",
        help="fail if the newest value of date or datetime column NAME is more than DURATION "
        "(36h, 2d, 1w) before the clock (SOURCE_DATE_EPOCH when set), for a stale export; "
        "repeatable",
    )
    gates.add_argument(
        "--utc-offset",
        type=_utc_offset,
        metavar="OFFSET",
        help="with --max-age: the UTC offset (Z, +HH:MM or -HH:MM) of the dates and times "
        "written without one; write a negative one with =, as --utc-offset=-04:00; without "
        "it such columns fail the check",
    )
    gates.add_argument(
        "--fail-on-schema-change",
        action="store_true",
        help="with --baseline: fail if columns were added or removed or changed type",
    )
    gates.add_argument(
        "--allow-type-change",
        type=_type_change_rule,
        action="append",
        default=[],
        metavar="[NAME=]FROM:TO",
        help="with --fail-on-schema-change: do not count a change of column type FROM to "
        "TO, such as int:float, in any column or only in NAME (inferred types: int, float, "
        "bool, date, datetime, string); repeatable",
    )
    gates.add_argument(
        "--allow-added-column",
        type=lambda text: _column_name(text, "--allow-added-column"),
        action="append",
        default=[],
        metavar="NAME",
        help="with --fail-on-schema-change: do not count column NAME as added since the "
        "baseline (exact, case-sensitive name); repeatable",
    )
    gates.add_argument(
        "--allow-removed-column",
        type=lambda text: _column_name(text, "--allow-removed-column"),
        action="append",
        default=[],
        metavar="NAME",
        help="with --fail-on-schema-change: do not count column NAME as removed since the "
        "baseline (exact, case-sensitive name); repeatable",
    )
    gates.add_argument(
        "--max-row-drop",
        type=_percentage,
        default=None,
        metavar="PCT",
        help="with --baseline: fail if the row count fell by more than PCT %% of the "
        "baseline's rows (0-100)",
    )
    gates.add_argument(
        "--max-missing-increase",
        type=_percentage,
        default=None,
        metavar="PCT",
        help="with --baseline: fail if a column's missing values rose by more than PCT "
        "percentage points (0-100)",
    )
    gates.add_argument(
        "--max-missing-increase-column",
        type=lambda text: _column_limit(text, "--max-missing-increase-column"),
        action="append",
        default=[],
        metavar="NAME=PCT",
        help="with --baseline: per-column limit in percentage points, overrides "
        "--max-missing-increase for NAME (repeatable)",
    )
    gates.add_argument(
        "--max-baseline-age",
        type=_duration,
        default=None,
        metavar="DURATION",
        help="with --baseline: fail if the baseline report is older than DURATION, a whole "
        "number with s, m, h, d or w (36h, 7d); the baseline needs the time --record-time "
        "writes",
    )
    gates.add_argument(
        "--max-duplicates",
        type=_non_negative_int,
        default=None,
        metavar="N",
        help="fail if the file has more than N duplicate rows (0: none allowed)",
    )
    gates.add_argument(
        "--min-rows",
        type=_positive_int,
        default=None,
        metavar="N",
        help="fail if the file has fewer than N data rows, such as an export that arrived "
        "with only its header",
    )
    return parser


def _check_selected(args: argparse.Namespace) -> None:
    """Raise ``ValueError`` when a per-column gate names a column left out by --columns."""
    if args.columns is None:
        return
    gates = (
        ("--max-missing-column", [name for name, _ in args.max_missing_column]),
        ("--require-type", [name for name, _ in args.require_type]),
        ("--max-affixes", [name for name, _ in args.max_affixes]),
        ("--range", [name for name, _ in args.range]),
        ("--max-missing-increase-column", [name for name, _ in args.max_missing_increase_column]),
        ("--unique", args.unique),
        ("--max-age", [name for name, _ in args.max_age]),
        ("--allowed-values", [name for name, _ in args.allowed_values]),
        ("--pattern", [name for name, _ in args.pattern]),
        ("--allow-type-change", [r.column for r in args.allow_type_change if r.column]),
        ("--allow-added-column", args.allow_added_column),
        ("--allow-removed-column", args.allow_removed_column),
    )
    for option, names in gates:
        for name in names:
            if name not in args.columns:
                raise ValueError(f"{option} checks column '{name}', which --columns leaves out")


def _same_file(first: Path, second: PathArg) -> bool:
    """Return whether two paths name the same existing file.

    Compares the device and inode numbers, so a different spelling of the path
    (``dir/../file``), a symbolic link and a hard link all count as the same file.
    A path that does not exist, or cannot be inspected, names no file to protect.
    """
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _check_output_path(args: argparse.Namespace) -> None:
    """Raise ``ValueError`` when --json-output would overwrite the input or the baseline."""
    if args.json_output is None:
        return
    inputs = (
        ("the input file", None if is_stdin(args.path) else args.path),
        ("the --baseline report", args.baseline),
    )
    for what, path in inputs:
        if path is not None and _same_file(args.json_output, path):
            raise ValueError(
                f"--json-output '{args.json_output}' is {what}; writing the report there "
                "would overwrite it (choose another file)"
            )


def _use_utf8_streams() -> None:
    """Write stdout and stderr as UTF-8 with ``\\n`` line endings on every platform (#120).

    On Windows a redirected stream (a pipe, ``> report.json``) uses the ANSI
    code page and CRLF: a report would not be UTF-8, a character outside the
    code page would crash the run, and the bytes would differ from the same
    run on Linux or macOS. Streams that are not text wrappers (a test's
    ``StringIO``) are left as they are.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors=stream.errors, newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    _use_utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    bool_words = tuple(dict.fromkeys(args.bool_words))  # repeated pairs count once
    try:
        check_thousands(args.thousands, args.decimal_comma)
        bool_word_map(bool_words)
        check_number_affixes(args.number_affix)
        if args.max_affixes and not args.number_affix:
            raise ValueError(
                "--max-affixes needs --number-affix (otherwise no affix is ever found)"
            )
        _check_selected(args)
        _check_output_path(args)
        if args.baseline is None:
            for option, given in (
                ("--fail-on-schema-change", args.fail_on_schema_change),
                ("--max-row-drop", args.max_row_drop is not None),
                ("--max-missing-increase", args.max_missing_increase is not None),
                ("--max-missing-increase-column", bool(args.max_missing_increase_column)),
                ("--allow-type-change", bool(args.allow_type_change)),
                ("--allow-added-column", bool(args.allow_added_column)),
                ("--allow-removed-column", bool(args.allow_removed_column)),
                ("--max-baseline-age", args.max_baseline_age is not None),
                ("--check-baseline-missing-rate", args.check_baseline_missing_rate),
            ):
                if given:
                    raise ValueError(f"{option} needs --baseline")
        if not args.fail_on_schema_change:
            for option, given, what in (
                ("--allow-type-change", args.allow_type_change, "type changes"),
                ("--allow-added-column", args.allow_added_column, "added columns"),
                ("--allow-removed-column", args.allow_removed_column, "removed columns"),
            ):
                if given:
                    raise ValueError(
                        f"{option} needs --fail-on-schema-change "
                        f"({what} only fail the run with that gate)"
                    )
        if args.min_rows is not None and args.max_rows is not None:
            if args.min_rows > args.max_rows:
                raise ValueError(
                    f"--min-rows {args.min_rows} can never pass with --max-rows {args.max_rows} "
                    "(only that many rows are read)"
                )
        if args.utc_offset is not None and not args.max_age:
            raise ValueError("--utc-offset needs --max-age (it only places times for that check)")
        if args.record_time and args.format != "json" and args.json_output is None:
            raise ValueError("--record-time needs a JSON report (--format json or --json-output)")
        # One reading of the clock: the stamp and the age check agree, and a
        # bad SOURCE_DATE_EPOCH is a usage error before the file is read.
        needs_clock = args.record_time or args.max_baseline_age is not None or args.max_age
        now = current_time() if needs_clock else None
    except ValueError as exc:
        parser.error(str(exc))
    try:
        # Read the baseline first: a wrong path should not cost a full profile.
        baseline = (
            None
            if args.baseline is None
            else load_baseline(args.baseline, check_missing_rate=args.check_baseline_missing_rate)
        )
        report = profile_file(
            args.path,
            max_rows=args.max_rows,
            delimiter=args.delimiter,
            decimal_comma=args.decimal_comma,
            na_tokens=args.na,
            top_n=args.top,
            encoding=args.encoding,
            max_field_size=args.max_field_size,
            thousands=args.thousands,
            date_order=args.date_order,
            bool_words=bool_words,
            number_affixes=tuple(args.number_affix),
            accounting_negatives=args.accounting_negatives,
            columns=args.columns,
            unique_keys=args.unique_key,
            allowed_values=dict(args.allowed_values),  # the last list for a name wins
            patterns=dict(args.pattern),  # the last pattern for a name wins
            skip_lines=args.skip_lines,
            skip_footer=args.skip_footer,
        )
    except CsvQualityError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.exit_code
    checks = evaluate(
        report,
        max_missing=args.max_missing,
        max_duplicates=args.max_duplicates,
        min_rows=args.min_rows,
        allowed_values=dict(args.allowed_values),
        patterns=dict(args.pattern),
        required_columns=args.require_columns,
        column_max_missing=dict(args.max_missing_column),  # the last limit for a name wins
        column_types=dict(args.require_type),  # the last type for a name wins
        column_max_affixes=dict(args.max_affixes),  # the last limit for a name wins
        column_ranges=dict(args.range),  # the last range for a name wins
        unique_columns=args.unique,  # a repeated name gives one check
        unique_keys=args.unique_key,  # a repeated key gives one check
        column_max_ages=dict(args.max_age),  # the last limit for a name wins
        now=now,
        utc_offset=args.utc_offset,
    )
    comparison = None if baseline is None else compare_reports(baseline, report)
    if comparison is not None:
        if args.fail_on_schema_change:
            checks.append(
                schema_change_check(
                    comparison,
                    args.allow_type_change,
                    args.allow_added_column,
                    args.allow_removed_column,
                )
            )
        if args.max_row_drop is not None:
            checks.append(row_drop_check(comparison, args.max_row_drop))
        if args.max_missing_increase is not None or args.max_missing_increase_column:
            checks.extend(
                missing_increase_checks(
                    comparison,
                    args.max_missing_increase,
                    dict(args.max_missing_increase_column),  # the last limit for a name wins
                )
            )
        if args.max_baseline_age is not None:
            assert now is not None  # read with the other usage checks
            checks.append(baseline_age_check(comparison, args.max_baseline_age, now))
    source = display_name(args.path)
    stamp = format_stamp(now) if args.record_time and now is not None else None
    if args.json_output is not None:
        try:
            write_atomic(args.json_output, render_json(report, source, checks, comparison, stamp))
        except OutputWriteError as exc:
            print(f"error: {exc.message}", file=sys.stderr)
            return exc.exit_code
    if args.format == "json":
        sys.stdout.write(render_json(report, source, checks, comparison, stamp))
    else:
        sys.stdout.write(render_markdown(report, source, checks, comparison))
    failed = [c for c in checks if not c.passed]
    for check in failed:
        print(f"check failed: {check.describe()}", file=sys.stderr)
    return EXIT_CHECKS if failed else 0
