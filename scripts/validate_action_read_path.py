"""Validate workspace boundaries for GitHub Action input and baseline paths."""

from __future__ import annotations

import sys
from pathlib import Path


def validate_read_path(raw: str, workspace_raw: str, label: str) -> None:
    """Reject filesystem reads outside the caller's workflow workspace."""
    if label not in {"path", "baseline"}:
        raise ValueError("path kind must be path or baseline")
    if not raw:
        raise ValueError(f"{label} must not be empty")
    if raw == "-":
        raise ValueError(f"{label} must name a file inside GITHUB_WORKSPACE")
    if "\n" in raw or "\r" in raw:
        raise ValueError(f"{label} must not contain line breaks")
    path = Path(raw)
    if path.is_absolute():
        raise ValueError(f"{label} must be relative to GITHUB_WORKSPACE")
    root = Path(workspace_raw).resolve()
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} must stay within GITHUB_WORKSPACE") from exc


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "usage: validate_action_read_path.py PATH WORKSPACE path|baseline",
            file=sys.stderr,
        )
        return 2
    try:
        validate_read_path(sys.argv[1], sys.argv[2], sys.argv[3])
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
