"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .errors import CsvQualityError
from .profile import build_report
from .reader import read_table
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
    """Accept one character, or a readable alias such as ``tab`` or ``semicolon``."""
    value = _DELIMITER_ALIASES.get(text.lower(), text)
    if len(value) != 1:
        raise argparse.ArgumentTypeError(
            f"invalid delimiter: {text!r} (use one character, or tab/comma/semicolon/pipe)"
        )
    if value in {'"', "\r", "\n"}:
        raise argparse.ArgumentTypeError(f"invalid delimiter: {text!r} (reserved character)")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m csv_quality_report",
        description="Quick data-quality report for a CSV file.",
    )
    parser.add_argument("path", type=Path, help="CSV file to analyze (UTF-8)")
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
        help="field separator: one character, or tab/comma/semicolon/pipe (default: ,)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        table = read_table(args.path, max_rows=args.max_rows, delimiter=args.delimiter)
    except CsvQualityError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.exit_code
    report = build_report(table)
    render = render_json if args.format == "json" else render_markdown
    sys.stdout.write(render(report, str(args.path)))
    return 0
