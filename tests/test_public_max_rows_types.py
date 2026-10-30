"""Direct Python CSV APIs must reject invalid row limits before file access."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.profile import profile_file
from csv_quality_report.reader import open_rows, read_table


def read_with(api: str, path: Path, max_rows: Any) -> tuple[int, bool]:
    """Return processed rows and truncation from all three public entrypoints."""
    if api == "stream":
        with open_rows(path, max_rows=max_rows) as stream:
            rows = list(stream)
            return len(rows), stream.truncated
    if api == "table":
        table = read_table(path, max_rows=max_rows)
        return len(table.rows), table.truncated
    report = profile_file(path, max_rows=max_rows)
    return report.rows, report.truncated


@pytest.mark.parametrize("api", ["stream", "table", "profile"])
@pytest.mark.parametrize(
    "invalid", [True, False, 1.0, 1.5, "1", math.nan, math.inf, -math.inf, object()]
)
def test_invalid_row_limit_fails_before_reading_missing_input(
    tmp_path: Path, api: str, invalid: Any
) -> None:
    with pytest.raises(ValueError, match="max_rows must be a non-negative integer or None"):
        read_with(api, tmp_path / "missing.csv", invalid)


@pytest.mark.parametrize("api", ["stream", "table", "profile"])
def test_negative_integer_row_limit_fails_before_opening_input(tmp_path: Path, api: str) -> None:
    with pytest.raises(ValueError, match="max_rows must be >= 0, got -1"):
        read_with(api, tmp_path / "missing.csv", -1)


@pytest.mark.parametrize("api", ["stream", "table", "profile"])
@pytest.mark.parametrize(
    ("max_rows", "expected"), [(None, (2, False)), (0, (0, True)), (1, (1, True))]
)
def test_unlimited_zero_and_positive_limits_preserve_rows(
    tmp_path: Path, api: str, max_rows: int | None, expected: tuple[int, bool]
) -> None:
    path = tmp_path / "records.csv"
    path.write_text("id,buyer\nS1,Andes\nS2,Paz\n", encoding="utf-8")
    assert read_with(api, path, max_rows) == expected
