"""Validate a fresh GitHub Action JSON artifact before exposing it as a report.

An exit code of 0 (or a quality-gate failure of 8) is not sufficient proof
that a usable CSV profile was generated. A previous report's fingerprint is
checked separately by report_freshness.py.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-standard JSON number: {value}")


def _finite_json_float(value: str) -> float:
    """Reject JSON numbers whose exponents overflow to nonfinite Python floats."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite JSON number")
    return number


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous duplicate JSON keys, including nested report objects."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _valid_column_accounting(column: dict[str, Any], rows: int) -> bool:
    """Check public CLI column counters without inspecting any source CSV."""
    missing = column.get("missing")
    distinct = column.get("distinct")
    untrimmed = column.get("untrimmed")
    missing_pct = column.get("missing_pct")
    top_values = column.get("top_values")
    # Narrow the numeric union for static typing and reject bool explicitly.
    if isinstance(missing_pct, bool) or not isinstance(missing_pct, (int, float)):
        return False
    if (
        type(missing) is not int
        or not 0 <= missing <= rows
        or type(distinct) is not int
        or not 0 <= distinct <= rows - missing
        or type(untrimmed) is not int
        or not 0 <= untrimmed <= rows - missing
        or not math.isfinite(missing_pct)
        or not 0 <= missing_pct <= 100
        or not isinstance(top_values, list)
    ):
        return False

    # Profile.round uses one decimal and zero on header-only files.
    expected_pct = round(100.0 * missing / rows, 1) if rows else 0.0
    if missing_pct != expected_pct or (distinct == 0) != (rows == missing):
        return False

    top_count = 0
    seen_values: set[str] = set()
    for item in top_values:
        if not isinstance(item, dict):
            return False
        value, count = item.get("value"), item.get("count")
        if (
            not isinstance(value, str)
            or value in seen_values
            or type(count) is not int
            or count <= 0
        ):
            return False
        seen_values.add(value)
        top_count += count
    return len(top_values) <= distinct and top_count <= rows - missing


def valid_report(path: Path, exit_code: int) -> bool:
    """Require the CLI's core report structure and matching quality status."""
    if exit_code not in (0, 8):
        return False
    try:
        data: Any = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite,
            parse_float=_finite_json_float,
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("source"), str):
        return False
    if type(data.get("rows")) is not int or data["rows"] < 0:
        return False
    if type(data.get("header_columns")) is not int or data["header_columns"] < 0:
        return False
    columns, checks = data.get("columns"), data.get("checks")
    if not isinstance(columns, list) or not all(
        isinstance(col, dict) and isinstance(col.get("name"), str) for col in columns
    ):
        return False
    if not isinstance(checks, list) or not all(
        isinstance(check, dict)
        and isinstance(check.get("check"), str)
        and type(check.get("passed")) is bool
        for check in checks
    ):
        return False
    # Profiling all columns preserves the header count; explicit --columns
    # selects a unique, ordered subset of the original CSV header.
    names = [col["name"] for col in columns]
    selected = data.get("selected_columns")
    duplicates = data.get("duplicate_rows")
    if (
        "selected_columns" not in data
        or len(names) != len(set(names))
        or len(names) > data["header_columns"]
        or type(duplicates) is not int
        or not 0 <= duplicates <= data["rows"]
    ):
        return False
    if selected is None:
        if len(names) != data["header_columns"]:
            return False
    elif (
        not isinstance(selected, list)
        or not all(isinstance(name, str) for name in selected)
        or selected != names
    ):
        return False
    if not all(_valid_column_accounting(column, data["rows"]) for column in columns):
        return False
    failed = any(not check["passed"] for check in checks)
    return failed == (exit_code == 8)


def main(argv: list[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else argv
    if len(values) != 2:
        print("usage: validate_action_report.py JSON_PATH EXIT_CODE", file=sys.stderr)
        return 2
    try:
        code = int(values[1])
    except ValueError:
        print("EXIT_CODE must be 0 or 8", file=sys.stderr)
        return 2
    if code not in (0, 8):
        print("EXIT_CODE must be 0 or 8", file=sys.stderr)
        return 2
    if not valid_report(Path(values[0]), code):
        print(
            "Action JSON report is invalid or its quality status disagrees with exit code",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
