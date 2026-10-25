"""Baseline metadata must be trustworthy before drift and schema comparisons."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.compare import compare_reports, load_baseline
from csv_quality_report.errors import FileReadError
from csv_quality_report.profile import profile_file


def _baseline() -> dict[str, Any]:
    return {
        "source": "previous.csv",
        "rows": 3,
        "columns": [
            {"name": "order", "type": "string", "missing_pct": 0.0, "missing": 0},
            {"name": "amount", "type": "int", "missing_pct": 33.3, "missing": 1},
        ],
    }


@pytest.mark.parametrize(
    ("alteration", "message"),
    [
        ({"rows": -1}, "no 'rows' count"),
        ({"rows": -100}, "no 'rows' count"),
        (
            {"columns": [
                {"name": "amount", "type": "int", "missing_pct": 0},
                {"name": "amount", "type": "string", "missing_pct": 100},
            ]},
            "duplicate baseline column name: 'amount'",
        ),
        (
            {"columns": [
                {"name": "Amount", "type": "int", "missing_pct": 0},
                {"name": "amount", "type": "int", "missing_pct": 0},
            ]},
            None,
        ),
    ],
)
def test_baseline_row_count_and_duplicate_labels(
    alteration: dict[str, Any], message: str | None, tmp_path: Path
) -> None:
    baseline = _baseline()
    baseline.update(alteration)
    target = tmp_path / "historical.json"
    target.write_text(json.dumps(baseline), encoding="utf-8")
    if message is None:
        assert load_baseline(target)["columns"] == alteration["columns"]
    else:
        with pytest.raises(FileReadError, match=message):
            load_baseline(target)


@pytest.mark.parametrize(
    "value", [-1.0, 100.1, math.nan, math.inf, -math.inf]
)
def test_invalid_missing_rates_are_rejected_before_drift_comparison(
    value: float, tmp_path: Path
) -> None:
    baseline = _baseline()
    baseline["columns"][0]["missing_pct"] = value
    target = tmp_path / "historical.json"
    target.write_text(json.dumps(baseline), encoding="utf-8")
    with pytest.raises(FileReadError, match="invalid 'missing_pct' \\(expected 0 to 100\\)"):
        load_baseline(target)


@pytest.mark.parametrize("value", [0, 100, 0.001, 99.999])
def test_valid_boundary_rates_preserve_normal_baseline_schema(
    value: float, tmp_path: Path
) -> None:
    baseline = _baseline()
    baseline["columns"][0]["missing_pct"] = value
    target = tmp_path / "historical.json"
    target.write_text(json.dumps(baseline), encoding="utf-8")
    assert load_baseline(target)["columns"][0]["missing_pct"] == value


def test_cli_rejects_corrupt_baseline_before_reading_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _baseline()
    baseline["columns"].append(
        {"name": "order", "type": "int", "missing_pct": 0}
    )
    target = tmp_path / "historical.json"
    target.write_text(json.dumps(baseline), encoding="utf-8")
    missing_input = tmp_path / "does-not-exist.csv"
    assert main([str(missing_input), "--baseline", str(target)]) == 3
    captured = capsys.readouterr()
    assert "duplicate baseline column name: 'order'" in captured.err
    assert captured.out == ""


def test_direct_comparison_refuses_ambiguous_history(write_csv: Any) -> None:
    baseline = _baseline()
    baseline["columns"].append(
        {"name": "amount", "type": "float", "missing_pct": 0}
    )
    report = profile_file(write_csv("order,amount\nO1,3\nO2,5\nO3,7\n"))
    with pytest.raises(ValueError, match="duplicate baseline column name"):
        compare_reports(baseline, report)
