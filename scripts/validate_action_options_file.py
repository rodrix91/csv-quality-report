"""Validate the GitHub Action's options-file input and copy what was checked (#325).

The file is parsed with the CLI's own parser (``csv_quality_report.optionsfile``,
from the Action's install), and each option gets the same guard as the
``args`` input in action.yml: ``--baseline`` and ``--json-output`` are reserved
for the Action's inputs, ``--help`` and ``--version`` exit 0 without reading
the CSV, and an options file cannot include another one.

The bytes that were validated are written to ``COPY``, and the Action passes
that copy to the CLI, so the file cannot change between the check and the run.
"""

from __future__ import annotations

import sys
from pathlib import Path

from csv_quality_report.cli import _options_file_matcher, build_parser
from csv_quality_report.optionsfile import (
    OptionsFileError,
    parse_options_bytes,
    read_options_bytes,
)

# The tokens action.yml refuses in args, written the same way: whole tokens
# for help and version (with their abbreviations), prefixes for the rest.
HELP_VERSION = frozenset(
    "-h --h --he --hel --help --v --ve --ver --vers --versi --versio --version".split()
)
RESERVED_PREFIXES = ("--ba", "--j")


def reserved_reason(token: str) -> str | None:
    """Why the Action refuses ``token`` in an options file, or ``None``."""
    if token in HELP_VERSION:
        return "help/version options are not supported in the Action"
    if token.startswith(RESERVED_PREFIXES):
        return (
            "use the Action baseline/report-path inputs; --baseline and --json-output are reserved"
        )
    return None


def validate_options_file(source: str, copy: str) -> list[str]:
    """Check the options file ``source`` and write its bytes to ``copy``.

    Returns its options. Raises ``ValueError`` with the line of the first
    problem.
    """
    data = read_options_bytes(source)
    tokens = parse_options_bytes(
        data, source, is_options_file=_options_file_matcher(build_parser())
    )
    for line, token in tokens:
        reason = reserved_reason(token)
        if reason is not None:
            raise ValueError(f"options-file '{source}': line {line}: {token}: {reason}")
    Path(copy).write_bytes(data)
    return [token for _, token in tokens]


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: validate_action_options_file.py OPTIONS_FILE COPY", file=sys.stderr)
        return 2
    try:
        validate_options_file(sys.argv[1], sys.argv[2])
    except (OptionsFileError, ValueError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
