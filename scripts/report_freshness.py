"""Detect stale Action report artifacts without modifying or deleting them.

Run before and after the CSV CLI. The CLI writes JSON atomically, so a newly
generated artifact has a changed file identity or metadata. A pre-existing
file whose fingerprint is unchanged is not evidence of a fresh result.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path


def report_fingerprint(path: Path) -> str:
    """Describe a regular report file without reading its private contents."""
    try:
        details = path.stat()
    except FileNotFoundError:
        return "missing"
    if not stat.S_ISREG(details.st_mode):
        return "not-file"
    return "file:" + ":".join(
        str(field)
        for field in (
            details.st_dev,
            details.st_ino,
            details.st_size,
            details.st_mtime_ns,
            details.st_ctime_ns,
        )
    )


def fresh_report(before: str, after: str) -> bool:
    """An existing report must change; a new one must be a regular file."""
    return after.startswith("file:") and after != before


def main(argv: list[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else argv
    if len(values) != 1:
        print("usage: report_freshness.py REPORT_PATH", file=sys.stderr)
        return 2
    try:
        print(report_fingerprint(Path(values[0])))
    except OSError:
        print("Cannot inspect JSON report file", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
