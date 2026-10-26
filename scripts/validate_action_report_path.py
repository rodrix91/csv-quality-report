"""Validate a user-supplied GitHub Action report path."""

from __future__ import annotations

import sys
from pathlib import Path


def validate_report_path(raw: str, workspace_raw: str) -> None:
    if "\n" in raw or "\r" in raw:
        raise ValueError("report-path must not contain line breaks")
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in raw):
        raise ValueError("report-path must not contain terminal control characters")
    path = Path(raw)
    if path.is_absolute():
        raise ValueError("report-path must be relative to GITHUB_WORKSPACE")
    workspace = Path(workspace_raw).resolve()
    resolved = (workspace / path).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("report-path must stay within GITHUB_WORKSPACE") from exc


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: validate_action_report_path.py REPORT_PATH WORKSPACE", file=sys.stderr)
        return 2
    try:
        validate_report_path(sys.argv[1], sys.argv[2])
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
