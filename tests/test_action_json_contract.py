"""A GitHub Action must verify a fresh JSON artifact before declaring success."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_action_report import main, valid_report

ROOT = Path(__file__).resolve().parents[1]


def _report(*, passed: bool = True) -> dict[str, object]:
    return {
        "source": "orders.csv",
        "rows": 2,
        "header_columns": 2,
        "selected_columns": None,
        "duplicate_rows": 0,
        "columns": [{"name": "id"}, {"name": "quantity"}],
        "checks": [{"check": "min_rows", "passed": passed}],
    }


def test_accepts_valid_passing_and_failed_gate_reports(tmp_path: Path) -> None:
    file = tmp_path / "report.json"
    for code, passed in ((0, True), (8, False)):
        file.write_text(json.dumps(_report(passed=passed)), encoding="utf-8")
        assert valid_report(file, code)
        assert main([str(file), str(code)]) == 0


@pytest.mark.parametrize(
    ("payload", "exit_code"),
    [
        ('{"rows": 2}', 0),
        ("[]", 0),
        ("null", 0),
        ("{", 0),
        ("", 0),
        ('{"rows": NaN}', 0),
        ('{"rows": Infinity}', 0),
        (json.dumps({**_report(), "rows": -1}), 0),
        (json.dumps({**_report(), "rows": True}), 0),
        (json.dumps({**_report(), "header_columns": -1}), 0),
        (json.dumps({**_report(), "header_columns": "2"}), 0),
        (json.dumps({**_report(), "source": 3}), 0),
        (json.dumps({**_report(), "columns": "invalid"}), 0),
        (json.dumps({**_report(), "columns": [{}]}), 0),
        (json.dumps({**_report(), "checks": {}}), 0),
        (json.dumps({**_report(), "checks": [{"check": "min_rows", "passed": 1}]}), 0),
        (json.dumps({**_report(), "checks": [{"passed": True}]}), 0),
        (json.dumps(_report(passed=False)), 0),
        (json.dumps(_report(passed=True)), 8),
        (json.dumps({**_report(), "checks": []}), 8),
    ],
)
def test_rejects_invalid_or_contradictory_reports(
    tmp_path: Path, payload: str, exit_code: int
) -> None:
    file = tmp_path / "report.json"
    file.write_text(payload, encoding="utf-8")
    assert not valid_report(file, exit_code)
    assert main([str(file), str(exit_code)]) == 3


@pytest.mark.parametrize(
    "change",
    [
        {"header_columns": 0},
        {"header_columns": 1},
        {"header_columns": 3},
        {"header_columns": True},
        {"duplicate_rows": None},
        {"duplicate_rows": -1},
        {"duplicate_rows": 3},
        {"duplicate_rows": True},
        {"duplicate_rows": "1"},
        {"selected_columns": "id"},
        {"selected_columns": ["id"]},
        {"selected_columns": ["quantity", "id"]},
        {"selected_columns": ["id", "id"]},
        {"columns": [{"name": "id"}, {"name": "id"}]},
        {"columns": [{"name": "id"}]},
        {"columns": [{"name": "id"}, {"name": "quantity"}, {"name": "extra"}]},
    ],
)
def test_rejects_inconsistent_column_accounting_and_duplicate_rows(
    tmp_path: Path, change: dict[str, object]
) -> None:
    file = tmp_path / "report.json"
    file.write_text(json.dumps({**_report(), **change}), encoding="utf-8")
    assert not valid_report(file, 0)
    assert main([str(file), "0"]) == 3


@pytest.mark.parametrize("removed", ["selected_columns", "duplicate_rows"])
def test_rejects_missing_column_and_duplicate_metadata(tmp_path: Path, removed: str) -> None:
    data = _report()
    del data[removed]
    file = tmp_path / "missing.json"
    file.write_text(json.dumps(data), encoding="utf-8")
    assert not valid_report(file, 0)


def test_accepts_genuine_selected_column_report_from_cli(tmp_path: Path) -> None:
    from csv_quality_report.cli import main as cli_main

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "id,quantity,region\nA,3,North\nA,3,North\nB,5,South\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    for selection in (None, "region,id"):
        args = [str(csv_path), "--json-output", str(output)]
        if selection is not None:
            args.extend(["--columns", selection])
        assert cli_main(args) == 0
        profile = json.loads(output.read_text(encoding="utf-8"))
        assert profile["rows"] == 3
        assert profile["duplicate_rows"] == 1
        assert profile["header_columns"] == 3
        assert [col["name"] for col in profile["columns"]] == (
            ["id", "quantity", "region"] if selection is None else ["region", "id"]
        )
        assert valid_report(output, 0)


def test_reports_with_no_quality_gates_are_valid_on_success(tmp_path: Path) -> None:
    file = tmp_path / "no-gates.json"
    file.write_text(json.dumps({**_report(), "checks": []}), encoding="utf-8")
    assert valid_report(file, 0)


def test_missing_non_utf8_and_non_file_reports_fail_closed(tmp_path: Path) -> None:
    assert not valid_report(tmp_path / "missing.json", 0)
    assert not valid_report(tmp_path, 0)
    bad = tmp_path / "non-utf8.json"
    bad.write_bytes(b"\xff")
    assert not valid_report(bad, 0)


@pytest.mark.parametrize("args", [[], ["only.json"], ["file.json", "invalid"], ["x", "3"]])
def test_invalid_invocations_remain_usage_errors(args: list[str]) -> None:
    assert main(args) == 2


def test_validator_is_packaged_and_action_exposes_only_verified_json() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    assert "include scripts/validate_action_report.py" in manifest
    script = action.split("      run: |\n", 1)[1]
    analyzer = script.index('python -m csv_quality_report "$INPUT_PATH"')
    freshness = script.index('report_after=$(python "$ACTION_PATH/scripts/report_freshness.py"')
    verification = script.index(
        'python "$ACTION_PATH/scripts/validate_action_report.py" "$json" "$code"'
    )
    exposed = script.index('report="$json"')
    finish = script.index('finish "$code" "$report" "$baseline_used"')
    assert analyzer < freshness < verification < exposed < finish
    assert "code=3" in script[verification:exposed]


def test_subprocess_returns_error_without_leaking_report_contents(tmp_path: Path) -> None:
    file = tmp_path / "secret.json"
    file.write_text('{"private":"never-expose-me"}', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_action_report.py"), str(file), "0"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 3
    assert "never-expose-me" not in result.stdout + result.stderr
