"""Public CSV field-size guards must not modify global csv state on invalid input."""

from __future__ import annotations

import csv
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.profile import profile_file
from csv_quality_report.reader import open_rows, read_table


def _read(api: str, path: Path, field_size: Any) -> int:
    if api == "stream":
        with open_rows(path, max_field_size=field_size) as stream:
            return len(list(stream))
    if api == "table":
        return len(read_table(path, max_field_size=field_size).rows)
    return profile_file(path, max_field_size=field_size).rows


@pytest.mark.parametrize("api", ["stream", "table", "profile"])
@pytest.mark.parametrize(
    ("invalid", "message"),
    [
        (True, "max_field_size must be a positive integer"),
        (False, "max_field_size must be a positive integer"),
        (1.0, "max_field_size must be a positive integer"),
        (1.5, "max_field_size must be a positive integer"),
        ("2", "max_field_size must be a positive integer"),
        (math.nan, "max_field_size must be a positive integer"),
        (math.inf, "max_field_size must be a positive integer"),
        (-math.inf, "max_field_size must be a positive integer"),
        (object(), "max_field_size must be a positive integer"),
        (0, "max_field_size must be between 1 and"),
        (-1, "max_field_size must be between 1 and"),
        (sys.maxsize + 1, "max_field_size must be between 1 and"),
        (10**400, "max_field_size must be between 1 and"),
    ],
)
def test_invalid_field_limit_rejected_before_file_access_and_global_change(
    tmp_path: Path, api: str, invalid: Any, message: str
) -> None:
    before = csv.field_size_limit()
    with pytest.raises(ValueError, match=message):
        _read(api, tmp_path / "absent.csv", invalid)
    assert csv.field_size_limit() == before


@pytest.mark.parametrize("api", ["stream", "table", "profile"])
@pytest.mark.parametrize("limit", [None, 128])
def test_supported_field_limits_preserve_data_and_global_limit(
    tmp_path: Path, api: str, limit: int | None
) -> None:
    path = tmp_path / "records.csv"
    path.write_text("id,region\nA1,Tarija\nA2,Jujuy\n", encoding="utf-8")
    before = csv.field_size_limit()
    assert _read(api, path, limit) == 2
    assert csv.field_size_limit() == before


def test_oversized_field_size_cli_argument_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "records.csv"
    path.write_text("id\nA1\n", encoding="utf-8")
    before = csv.field_size_limit()
    with pytest.raises(SystemExit) as caught:
        main([str(path), "--max-field-size", str(sys.maxsize + 1)])
    assert caught.value.code == 2
    assert f"must be <= {sys.maxsize}" in capsys.readouterr().err
    assert csv.field_size_limit() == before
