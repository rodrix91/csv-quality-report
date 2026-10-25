"""Optional consistency auditing for counts and rounded baseline missing rates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.compare import compare_reports, load_baseline
from csv_quality_report.errors import FileReadError
from csv_quality_report.profile import profile_file


def _baseline(rows: int = 3, missing: int | None = 1, rate: float = 33.3) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": "sku", "type": "string", "missing_pct": rate}
    if missing is not None:
        entry["missing"] = missing
    return {"source": "previous.csv", "rows": rows, "columns": [entry]}


def _save(tmp_path: Path, baseline: dict[str, Any]) -> Path:
    path = tmp_path / "historical.json"
    path.write_text(json.dumps(baseline), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("rows", "missing", "rate"),
    [
        (3, 0, 33.3),
        (3, 1, 0),
        (3, 1, 100),
        (3, 3, 33.3),
        (0, 0, 50),
        (3, 1, 33.39),
    ],
)
def test_opt_in_rate_check_rejects_contradictory_baselines(
    rows: int, missing: int, rate: float, tmp_path: Path
) -> None:
    path = _save(tmp_path, _baseline(rows, missing, rate))
    with pytest.raises(FileReadError, match="inconsistent with its 'missing' count"):
        load_baseline(path, check_missing_rate=True)


@pytest.mark.parametrize(
    ("rows", "missing", "rate"),
    [
        (3, 0, 0.0),
        (3, 1, 33.3),
        (3, 1, 33.3333333),
        (3, 3, 100.0),
        (0, 0, 0.0),
        (1500, 1, 0.1),
    ],
)
def test_opt_in_rate_check_accepts_correct_counts_and_display_rounding(
    rows: int, missing: int, rate: float, tmp_path: Path
) -> None:
    path = _save(tmp_path, _baseline(rows, missing, rate))
    assert load_baseline(path, check_missing_rate=True)["columns"][0]["missing_pct"] == rate


def test_default_mode_preserves_legacy_rate_count_behavior(
    tmp_path: Path, write_csv: Any
) -> None:
    legacy = _baseline(missing=0, rate=100)
    path = _save(tmp_path, legacy)
    assert load_baseline(path) == legacy
    current = profile_file(write_csv("sku\\nS1\\nS2\\nS3\\n"))
    assert compare_reports(legacy, current).rows_before == 3
    with pytest.raises(ValueError, match="inconsistent with its 'missing' count"):
        compare_reports(legacy, current, check_missing_rate=True)


def test_strict_mode_does_not_require_missing_count_for_old_reports(tmp_path: Path) -> None:
    legacy = _baseline(missing=None, rate=33.3)
    path = _save(tmp_path, legacy)
    assert load_baseline(path, check_missing_rate=True) == legacy


def test_strict_cli_rejects_bad_baseline_before_reading_csv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _save(tmp_path, _baseline(missing=0, rate=100))
    no_csv = tmp_path / "not-present.csv"
    code = main([str(no_csv), "--baseline", str(path), "--check-baseline-missing-rate"])
    output = capsys.readouterr()
    assert code == 3
    assert "inconsistent with its 'missing' count" in output.err
    assert output.out == ""


def test_strict_cli_requires_baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="2"):
        main([str(tmp_path / "missing.csv"), "--check-baseline-missing-rate"])
    assert "--check-baseline-missing-rate needs --baseline" in capsys.readouterr().err


def test_strict_cli_accepts_baseline_with_normal_rounding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _save(tmp_path, _baseline())
    csv = tmp_path / "input.csv"
    csv.write_text("sku\\nS1\\n\\nS3\\n", encoding="utf-8")
    code = main(
        [str(csv), "--baseline", str(path), "--check-baseline-missing-rate", "--format", "json"]
    )
    output = capsys.readouterr()
    assert code == 0, output.err
    assert json.loads(output.out)["baseline"] is not None
