"""Strict public Python API validation for CSV title/footer skip counts."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.profile import profile_file
from csv_quality_report.reader import open_rows, read_table


def invoke(api: str, path: Path, option: str, value: Any) -> None:
    """Call each public reader without accessing the file for an invalid count."""
    kwargs: dict[str, Any] = {option: value}
    if api == "stream":
        with open_rows(path, **kwargs):
            pass
    elif api == "table":
        read_table(path, **kwargs)
    else:
        profile_file(path, **kwargs)


@pytest.mark.parametrize("api", ["stream", "table", "profile"])
@pytest.mark.parametrize("option", ["skip_lines", "skip_footer"])
@pytest.mark.parametrize(
    "invalid", [True, False, 1.0, 1.5, "1", None, math.nan, math.inf, -math.inf]
)
def test_invalid_skip_count_is_rejected_before_opening_missing_csv(
    tmp_path: Path, api: str, option: str, invalid: Any
) -> None:
    # A missing input must not mask an invalid option, even when False resembles zero.
    with pytest.raises(ValueError, match=f"{option} must be a non-negative integer"):
        invoke(api, tmp_path / "does-not-exist.csv", option, invalid)


@pytest.mark.parametrize("api", ["stream", "table", "profile"])
@pytest.mark.parametrize("option", ["skip_lines", "skip_footer"])
def test_negative_integer_skip_count_keeps_legacy_error(
    tmp_path: Path, api: str, option: str
) -> None:
    with pytest.raises(ValueError, match=f"{option} must be >= 0, got -1"):
        invoke(api, tmp_path / "does-not-exist.csv", option, -1)


@pytest.mark.parametrize("api", ["stream", "table", "profile"])
def test_valid_zero_and_positive_skip_counts_preserve_data(
    tmp_path: Path, api: str
) -> None:
    path = tmp_path / "export.csv"
    path.write_text("Report title\nid,buyer\nS1,Andes\nS2,Paz\nTotal\n", encoding="utf-8")

    if api == "stream":
        with open_rows(path, skip_lines=1, skip_footer=1) as data:
            assert data.header == ["id", "buyer"]
            assert list(data) == [["S1", "Andes"], ["S2", "Paz"]]
            assert (data.skipped_lines, data.skipped_footer) == (1, 1)
    elif api == "table":
        table = read_table(path, skip_lines=1, skip_footer=1)
        assert table.rows == [["S1", "Andes"], ["S2", "Paz"]]
        assert (table.skipped_lines, table.skipped_footer) == (1, 1)
    else:
        report = profile_file(path, skip_lines=1, skip_footer=1)
        assert report.rows == 2
        assert (report.skipped_lines, report.skipped_footer) == (1, 1)
