"""Validate reusable GitHub Action option strings before Bash tokenization.

Bash's 'read -a' consumes one line: a second line of quality gates would
otherwise be ignored while the first line could still report success.
"""

from __future__ import annotations

import os
import sys


def validate_action_args(raw: str, label: str) -> None:
    """Reject multiline and terminal-control inputs; keep tab separators."""
    if "\r" in raw or "\n" in raw:
        raise ValueError(f"{label} must be a single line")
    if any((ord(char) < 32 and char != "\t") or 127 <= ord(char) <= 159 for char in raw):
        raise ValueError(f"{label} must not contain terminal control characters")


def main() -> int:
    for variable, label in (
        ("INPUT_ARGS", "args"),
        ("INPUT_BASELINE_ARGS", "baseline-args"),
    ):
        try:
            validate_action_args(os.environ.get(variable, ""), label)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
