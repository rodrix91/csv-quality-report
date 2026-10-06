"""Command-line entry point."""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from . import __version__
from .checks import COLUMN_TYPES, Bound, ValueRange, evaluate, schema_change_check
from .compare import compare_reports, load_baseline
from .errors import EXIT_CHECKS, CsvQualityError, OutputWriteError
from .inference import DATE_ORDERS, bool_word_map, check_number_affixes, check_thousands
from .profile import TOP_N, profile_file
from .reader import DEFAULT_ENCODING, DELIMITER_AUTO, display_name, normalize_encoding
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


def _non_negative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return value


def _column_limit(text: str) -> tuple[str, float]:
    """Parse ``NAME=PCT``; the last ``=`` separates them, so names may contain ``=``."""
    name, sep, value = text.rpartition("=")
    if not sep or not name:
        raise argparse.ArgumentTypeError(
            f"invalid --max-missing-column value: {text!r} (use NAME=PCT)"
        )
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


def _bound(text: str, option: str) -> Bound:
    """One side of a ``--range``: empty (open), an ISO date, or a finite number."""
    if not text:
        return None
    if _ISO_DATE_RE.fullmatch(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"invalid --range value: {option!r} ({text!r} is not a valid date)"
            ) from None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid --range value: {option!r} ({text!r} is not a number or a YYYY-MM-DD date)"
        ) from None
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError(
            f"invalid --range value: {option!r} ({text!r} is not a finite number)"
        )
    return number


def _column_range(text: str) -> tuple[str, ValueRange]:
    """Parse ``NAME=MIN:MAX``; either bound may be empty, names may contain ``=``."""
    name, sep, spec = text.rpartition("=")
    if not sep or not name or spec.count(":") != 1:
        raise argparse.ArgumentTypeError(
            f"invalid --range value: {text!r} (use NAME=MIN:MAX; one side may be empty)"
        )
    low_text, high_text = spec.split(":")
    low, high = _bound(low_text.strip(), text), _bound(high_text.strip(), text)
    if low is None and high is None:
        raise argparse.ArgumentTypeError(f"invalid --range value: {text!r} (give MIN, MAX or both)")
    if low is not None and high is not None:
        if isinstance(low, date) and isinstance(high, date):
            reversed_bounds = low > high
        elif not isinstance(low, date) and not isinstance(high, date):
            reversed_bounds = low > high
        else:
            raise argparse.ArgumentTypeError(
                f"invalid --range value: {text!r} (both bounds must be numbers, or both dates)"
            )
        if reversed_bounds:
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


def _column_names(text: str, option: str = "--require-columns") -> tuple[str, ...]:
    """Parse ``id,date,weight`` into unique, stripped, non-empty names (order kept)."""
    names = tuple(dict.fromkeys(n.strip() for n in text.split(",") if n.strip()))
    if not names:
        raise argparse.ArgumentTypeError(f"invalid {option} value: {text!r} (no names)")
    return names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m csv_quality_report",
        description="Quick data-quality report for a CSV file.",
    )
    parser.add_argument(
        "path",
        type=Path,
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
        "--columns",
        type=lambda text: _column_names(text, "--columns"),
        default=None,
        metavar="NAMES",
        help="profile only these comma-separated columns, in this order (rows are still read "
        "whole: duplicates compare full rows, --require-columns checks the full header)",
    )
    gates.add_argument(
        "--require-columns",
        type=_column_names,
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
        help="fail if column NAME has values outside MIN..MAX (inclusive; numbers, or "
        "YYYY-MM-DD dates for date columns; one side may be empty); repeatable",
    )
    gates.add_argument(
        "--fail-on-schema-change",
        action="store_true",
        help="with --baseline: fail if columns were added or removed or changed type",
    )
    gates.add_argument(
        "--max-duplicates",
        type=_non_negative_int,
        default=None,
        metavar="N",
        help="fail if the file has more than N duplicate rows (0: none allowed)",
    )
    return parser


def _write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` as UTF-8, raising ``OutputWriteError`` on failure."""
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise OutputWriteError(f"cannot write '{path}': {exc.strerror or exc}") from exc


def _check_selected(args: argparse.Namespace) -> None:
    """Raise ``ValueError`` when a per-column gate names a column left out by --columns."""
    if args.columns is None:
        return
    gates = (
        ("--max-missing-column", [name for name, _ in args.max_missing_column]),
        ("--require-type", [name for name, _ in args.require_type]),
        ("--max-affixes", [name for name, _ in args.max_affixes]),
        ("--range", [name for name, _ in args.range]),
    )
    for option, names in gates:
        for name in names:
            if name not in args.columns:
                raise ValueError(f"{option} checks column '{name}', which --columns leaves out")


def main(argv: Sequence[str] | None = None) -> int:
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
        if args.fail_on_schema_change and args.baseline is None:
            raise ValueError("--fail-on-schema-change needs --baseline")
    except ValueError as exc:
        parser.error(str(exc))
    try:
        # Read the baseline first: a wrong path should not cost a full profile.
        baseline = None if args.baseline is None else load_baseline(args.baseline)
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
        )
    except CsvQualityError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.exit_code
    checks = evaluate(
        report,
        max_missing=args.max_missing,
        max_duplicates=args.max_duplicates,
        required_columns=args.require_columns,
        column_max_missing=dict(args.max_missing_column),  # the last limit for a name wins
        column_types=dict(args.require_type),  # the last type for a name wins
        column_max_affixes=dict(args.max_affixes),  # the last limit for a name wins
        column_ranges=dict(args.range),  # the last range for a name wins
    )
    comparison = None if baseline is None else compare_reports(baseline, report)
    if comparison is not None and args.fail_on_schema_change:
        checks.append(schema_change_check(comparison))
    source = display_name(args.path)
    if args.json_output is not None:
        try:
            _write_text(args.json_output, render_json(report, source, checks, comparison))
        except OutputWriteError as exc:
            print(f"error: {exc.message}", file=sys.stderr)
            return exc.exit_code
    render = render_json if args.format == "json" else render_markdown
    sys.stdout.write(render(report, source, checks, comparison))
    failed = [c for c in checks if not c.passed]
    for check in failed:
        print(f"check failed: {check.describe()}", file=sys.stderr)
    return EXIT_CHECKS if failed else 0
