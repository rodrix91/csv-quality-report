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
            {
                "columns": [
                    {"name": "amount", "type": "int", "missing_pct": 0},
                    {"name": "amount", "type": "string", "missing_pct": 100},
                ]
            },
            "duplicate baseline column name: 'amount'",
        ),
        (
            {
                "columns": [
                    {"name": "Amount", "type": "int", "missing_pct": 0},
                    {"name": "amount", "type": "int", "missing_pct": 0},
                ]
            },
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


@pytest.mark.parametrize("value", [-1.0, 100.1, math.nan, math.inf, -math.inf, 10**400])
def test_invalid_missing_rates_are_rejected_before_drift_comparison(
    value: float | int, tmp_path: Path
) -> None:
    baseline = _baseline()
    baseline["columns"][0]["missing_pct"] = value
    target = tmp_path / "historical.json"
    target.write_text(json.dumps(baseline), encoding="utf-8")
    message = (
        "non-standard baseline JSON numeric constant"
        if isinstance(value, float) and not math.isfinite(value)
        else r"invalid 'missing_pct' \(expected 0 to 100\)"
    )
    with pytest.raises(FileReadError, match=message):
        load_baseline(target)


@pytest.mark.parametrize("value", [0, 100, 0.001, 99.999])
def test_valid_boundary_rates_preserve_normal_baseline_schema(value: float, tmp_path: Path) -> None:
    baseline = _baseline()
    baseline["columns"][0]["missing_pct"] = value
    target = tmp_path / "historical.json"
    target.write_text(json.dumps(baseline), encoding="utf-8")
    assert load_baseline(target)["columns"][0]["missing_pct"] == value


def test_cli_rejects_corrupt_baseline_before_reading_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _baseline()
    baseline["columns"].append({"name": "order", "type": "int", "missing_pct": 0})
    target = tmp_path / "historical.json"
    target.write_text(json.dumps(baseline), encoding="utf-8")
    missing_input = tmp_path / "does-not-exist.csv"
    assert main([str(missing_input), "--baseline", str(target)]) == 3
    captured = capsys.readouterr()
    assert "duplicate baseline column name: 'order'" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    ("rows", "missing"),
    [(3, 4), (3, 10**400), (0, 1)],
)
def test_baseline_rejects_more_missing_cells_than_rows(
    rows: int, missing: int, tmp_path: Path
) -> None:
    baseline = _baseline()
    baseline["rows"] = rows
    baseline["columns"][0]["missing"] = missing
    target = tmp_path / "impossible-baseline.json"
    target.write_text(json.dumps(baseline), encoding="utf-8")
    with pytest.raises(FileReadError, match="has more missing cells"):
        load_baseline(target)


def test_missing_count_equal_to_rows_is_valid(tmp_path: Path) -> None:
    baseline = _baseline()
    baseline["columns"][0]["missing"] = baseline["rows"]
    baseline["columns"][0]["missing_pct"] = 100
    target = tmp_path / "all-missing-baseline.json"
    target.write_text(json.dumps(baseline), encoding="utf-8")
    loaded = load_baseline(target)
    assert loaded["columns"][0]["missing"] == 3


def test_cli_rejects_impossible_baseline_before_csv_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _baseline()
    baseline["columns"][1]["missing"] = 4
    target = tmp_path / "impossible-baseline.json"
    target.write_text(json.dumps(baseline), encoding="utf-8")
    assert main([str(tmp_path / "missing-input.csv"), "--baseline", str(target)]) == 3
    output = capsys.readouterr()
    assert "more missing cells (4) than rows (3)" in output.err
    assert output.out == ""


def test_direct_comparison_rejects_impossible_baseline_count(write_csv: Any) -> None:
    baseline = _baseline()
    baseline["columns"][1]["missing"] = 5
    report = profile_file(write_csv("order,amount\\nO1,3\\nO2,5\\nO3,7\\n"))
    with pytest.raises(ValueError, match="more missing cells"):
        compare_reports(baseline, report)


def test_direct_comparison_refuses_ambiguous_history(write_csv: Any) -> None:
    baseline = _baseline()
    baseline["columns"].append({"name": "amount", "type": "float", "missing_pct": 0})
    report = profile_file(write_csv("order,amount\nO1,3\nO2,5\nO3,7\n"))
    with pytest.raises(ValueError, match="duplicate baseline column name"):
        compare_reports(baseline, report)


@pytest.mark.parametrize(
    ("payload", "duplicate"),
    [
        ('{"rows":3,"rows":0,"columns":[]}', "rows"),
        (
            '{"rows":3,"columns":[{"name":"sku","type":"string",'
            '"missing_pct":0,"missing_pct":100}]}',
            "missing_pct",
        ),
        (
            '{"rows":3,"columns":[],"metadata":{"revision":1,"revision":1}}',
            "revision",
        ),
        (r'{"rows":3,"ro\u0077s":0,"columns":[]}', "rows"),
    ],
)
def test_duplicate_baseline_json_members_are_rejected_before_last_wins(
    payload: str, duplicate: str, tmp_path: Path
) -> None:
    path = tmp_path / "duplicate-members.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(FileReadError, match=f"duplicate baseline JSON key: '{duplicate}'"):
        load_baseline(path)


def test_duplicate_baseline_members_fail_before_csv_and_preserve_existing_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "ambiguous-baseline.json"
    path.write_text('{"rows":3,"rows":0,"columns":[]}', encoding="utf-8")
    previous = tmp_path / "verified-report.json"
    previous.write_text('{"status":"verified"}\n', encoding="utf-8")
    exit_code = main(
        [
            str(tmp_path / "unreadable-input.csv"),
            "--baseline",
            str(path),
            "--format",
            "json",
            "--json-output",
            str(previous),
        ]
    )
    output = capsys.readouterr()
    assert exit_code == 3
    assert "duplicate baseline JSON key: 'rows'" in output.err
    assert "unreadable-input.csv" not in output.err
    assert output.out == ""
    assert previous.read_text(encoding="utf-8") == '{"status":"verified"}\n'


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e309", "-1e309"])
@pytest.mark.parametrize("placement", ["root", "nested", "column"])
def test_nonfinite_baseline_json_numbers_are_rejected_everywhere(
    token: str, placement: str, tmp_path: Path
) -> None:
    """Never trust non-JSON constants or silently overflowed numeric metadata."""
    if placement == "root":
        content = '{"rows":3,"columns":[],"unexpected":' + token + "}"
    elif placement == "nested":
        content = '{"rows":3,"columns":[],"metadata":{"limit":' + token + "}}"
    else:
        content = (
            '{"rows":3,"columns":[{"name":"sku","type":"string",'
            '"missing_pct":0,"unexpected":' + token + "}]}"
        )
    target = tmp_path / "nonfinite-baseline.json"
    target.write_text(content, encoding="utf-8")
    expected = (
        "non-standard baseline JSON numeric constant"
        if token in ("NaN", "Infinity", "-Infinity")
        else "non-finite baseline JSON numeric value"
    )
    with pytest.raises(FileReadError, match=expected):
        load_baseline(target)


def test_valid_numeric_metadata_and_quoted_special_text_still_load(tmp_path: Path) -> None:
    target = tmp_path / "valid-baseline.json"
    target.write_text(
        '{"rows":3,"columns":[{"name":"sku","type":"string","missing_pct":0.0}],'
        '"metadata":{"label":"NaN","limit":1e2,"threshold":-0.05}}',
        encoding="utf-8",
    )
    loaded = load_baseline(target)
    assert loaded["columns"][0]["missing_pct"] == 0.0
    assert loaded["metadata"] == {"label": "NaN", "limit": 100.0, "threshold": -0.05}


def test_cli_rejects_nonfinite_historical_metadata_before_csv_and_preserves_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = tmp_path / "not-a-standard-json-baseline.json"
    baseline.write_text('{"rows":3,"columns":[],"metadata":{"limit":NaN}}', encoding="utf-8")
    verified = tmp_path / "previously-verified.json"
    verified.write_text('{"source":"untouched"}\n', encoding="utf-8")
    code = main(
        [
            str(tmp_path / "missing-input.csv"),
            "--baseline",
            str(baseline),
            "--format",
            "json",
            "--json-output",
            str(verified),
        ]
    )
    printed = capsys.readouterr()
    assert code == 3
    assert "non-standard baseline JSON numeric constant: NaN" in printed.err
    assert "missing-input.csv" not in printed.err
    assert printed.out == ""
    assert verified.read_text(encoding="utf-8") == '{"source":"untouched"}\n'
