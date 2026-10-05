"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .errors import CsvQualityError
from .profile import profile_file
from .reader import DELIMITER_AUTO
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m csv_quality_report",
        description="Quick data-quality report for a CSV file.",
    )
    parser.add_argument("path", type=Path, help="CSV file to analyze (UTF-8)")
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
        "--na",
        type=_na_tokens,
        default=(),
        metavar="TOKENS",
        help="comma-separated cell values to count as missing, e.g. NA,null,- (case-sensitive)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = profile_file(
            args.path,
            max_rows=args.max_rows,
            delimiter=args.delimiter,
            decimal_comma=args.decimal_comma,
            na_tokens=args.na,
        )
    except CsvQualityError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.exit_code
    render = render_json if args.format == "json" else render_markdown
    sys.stdout.write(render(report, str(args.path)))
    return 0
