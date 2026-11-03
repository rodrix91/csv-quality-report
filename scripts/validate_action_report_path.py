"""Validate a user-supplied GitHub Action report path."""

from __future__ import annotations

import sys
from pathlib import Path


def validate_report_path(raw: str, workspace_raw: str) -> None:
    if not raw.strip():
        raise ValueError("report-path must name a JSON file inside GITHUB_WORKSPACE")
    if raw.endswith(("/", "\\")):
        raise ValueError("report-path must name a file, not a directory")
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
    # Existing directories, FIFOs and devices cannot be atomic JSON report
    # destinations. Reject before the Action runs its expensive CSV analysis.
    if resolved.exists() and not resolved.is_file():
        raise ValueError("report-path must name a regular file, not a directory or device")


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
