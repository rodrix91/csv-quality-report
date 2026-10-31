"""The reusable Action must reject impossible per-column CSV statistics."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from csv_quality_report.cli import main as cli_main
from scripts.validate_action_report import valid_report


def _report() -> dict[str, object]:
    return {
        "source": "orders.csv",
        "rows": 4,
        "header_columns": 1,
        "selected_columns": None,
        "duplicate_rows": 0,
        "columns": [
            {
                "name": "id",
                "missing": 1,
                "missing_pct": 25.0,
                "distinct": 2,
                "untrimmed": 1,
                "top_values": [
                    {"value": "A", "count": 2},
                    {"value": "B", "count": 1},
                ],
            }
        ],
        "checks": [],
    }


def _valid(tmp_path: Path, report: dict[str, object], code: int = 0) -> bool:
    path = tmp_path / "quality.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return valid_report(path, code)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("missing", True),
        ("missing", -1),
        ("missing", 5),
        ("missing", "1"),
        ("missing", 2),
        ("distinct", -1),
        ("distinct", 4),
        ("distinct", True),
        ("distinct", 0),
        ("untrimmed", -1),
        ("untrimmed", 4),
        ("untrimmed", True),
        ("missing_pct", -1),
        ("missing_pct", 101),
        ("missing_pct", 25.1),
        ("missing_pct", True),
        ("missing_pct", "25"),
        ("missing_pct", math.inf),
        ("missing_pct", math.nan),
        ("top_values", None),
        ("top_values", {}),
        ("top_values", ["A"]),
        ("top_values", [{"value": "A", "count": 4}]),
        ("top_values", [{"value": "A", "count": True}]),
        ("top_values", [{"value": "A", "count": 0}]),
        ("top_values", [{"value": "A", "count": 1.5}]),
        ("top_values", [{"value": 3, "count": 1}]),
        ("top_values", [{"value": "A", "count": 2}, {"value": "A", "count": 1}]),
        (
            "top_values",
            [
                {"value": "A", "count": 1},
                {"value": "B", "count": 1},
                {"value": "C", "count": 1},
            ],
        ),
    ],
)
def test_rejects_impossible_or_mistyped_column_metrics(
    tmp_path: Path, key: str, value: object
) -> None:
    report = _report()
    columns = report["columns"]
    assert isinstance(columns, list)
    columns[0][key] = value
    assert not _valid(tmp_path, report), (key, value)


@pytest.mark.parametrize(
    "removed",
    ["missing", "missing_pct", "distinct", "untrimmed", "top_values"],
)
def test_rejects_missing_column_counters(tmp_path: Path, removed: str) -> None:
    report = _report()
    columns = report["columns"]
    assert isinstance(columns, list)
    del columns[0][removed]
    assert not _valid(tmp_path, report)


def test_valid_top_zero_and_all_missing_or_header_only_rows(tmp_path: Path) -> None:
    assert _valid(tmp_path, _report())
    cases: tuple[tuple[int, int, float, int, list[dict[str, object]]], ...] = (
        (0, 0, 0.0, 0, []),
        (2, 2, 100.0, 0, []),
        (4, 1, 25.0, 2, []),
    )
    for rows, missing, missing_pct, distinct, top_values in cases:
        report = _report()
        report["rows"] = rows
        columns = report["columns"]
        assert isinstance(columns, list)
        column = columns[0]
        column.update(
            missing=missing,
            missing_pct=missing_pct,
            distinct=distinct,
            top_values=top_values,
            untrimmed=0,
        )
        assert _valid(tmp_path, report), (rows, missing, top_values)


@pytest.mark.parametrize(
    ("data", "extra", "expected"),
    [
        ("a,b\n", [], 0),
        ("a,b\n,\n,\n", [], 0),
        ("a,b\n1,x\n2,y\n", ["--columns", "a"], 0),
        ("a,b\n1,x\n2,y\n", ["--top", "0"], 0),
        ("a,b\n1,x\n2,y\n", ["--max-rows", "1"], 0),
        ("a,b\n1,x\n2,y\n", ["--max-missing", "0"], 0),
        ("a,b\n,x\n2,y\n", ["--max-missing", "0"], 8),
    ],
)
def test_real_cli_report_remains_accepted(
    tmp_path: Path, data: str, extra: list[str], expected: int
) -> None:
    csv_path = tmp_path / "rows.csv"
    json_path = tmp_path / "report.json"
    csv_path.write_text(data, encoding="utf-8")
    assert cli_main([str(csv_path), *extra, "--json-output", str(json_path)]) == expected
    assert valid_report(json_path, expected)


def test_a_counter_change_can_not_silently_corrupt_an_otherwise_valid_report(
    tmp_path: Path,
) -> None:
    pristine = _report()
    assert _valid(tmp_path, pristine)
    altered = copy.deepcopy(pristine)
    columns = altered["columns"]
    assert isinstance(columns, list)
    columns[0]["missing_pct"] = 0.0
    assert not _valid(tmp_path, altered)
