"""Do not amplify untrusted historical JSON fields into CLI or CI logs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from csv_quality_report.cli import main
from csv_quality_report.compare import load_baseline
from csv_quality_report.errors import FileReadError


def test_long_duplicate_json_key_has_a_short_escaped_error(tmp_path: Path) -> None:
    key = "unexpected-" + "X" * 80_000 + "-private-tail"
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"rows":1,"columns":[],' + json.dumps(key) + ':1,'
        + json.dumps(key) + ':2}',
        encoding="utf-8",
    )
    with pytest.raises(FileReadError, match="duplicate baseline JSON key") as error:
        load_baseline(path)
    diagnostic = str(error.value)
    assert len(diagnostic) < 400
    assert "[truncated]" in diagnostic
    assert "-private-tail" not in diagnostic


def test_nonfinite_huge_exponent_is_not_copied_to_error(tmp_path: Path) -> None:
    path = tmp_path / "nonfinite.json"
    path.write_text(
        '{"rows":0,"columns":[],"extra":1e' + "9" * 20_000 + "}",
        encoding="utf-8",
    )
    with pytest.raises(FileReadError, match="non-finite baseline JSON numeric") as error:
        load_baseline(path)
    diagnostic = str(error.value)
    assert len(diagnostic) < 400
    assert "[truncated]" in diagnostic
    assert "9" * 300 not in diagnostic


def test_malformed_column_name_is_bounded_before_cli_reads_csv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    long_name = "secret" + "A" * 50_000 + "hidden-last-field"
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "rows": 1,
                "columns": [
                    {"name": long_name, "type": "string", "missing_pct": 101}
                ],
            }
        ),
        encoding="utf-8",
    )
    previous = tmp_path / "verified.json"
    previous.write_text('{"verified":true}\n', encoding="utf-8")
    assert main([
        str(tmp_path / "missing.csv"), "--baseline", str(baseline),
        "--format", "json", "--json-output", str(previous),
    ]) == 3
    captured = capsys.readouterr()
    assert "invalid 'missing_pct'" in captured.err
    assert "[truncated]" in captured.err
    assert "hidden-last-field" not in captured.err
    assert "missing.csv" not in captured.err
    assert len(captured.err) < 450
    assert captured.out == ""
    assert previous.read_text(encoding="utf-8") == '{"verified":true}\n'


def test_short_user_column_names_keep_original_diagnostics(tmp_path: Path) -> None:
    baseline = tmp_path / "short.json"
    baseline.write_text(
        '{"rows":1,"columns":[{"name":"importe","type":"float",'
        '"missing_pct":105}]}',
        encoding="utf-8",
    )
    with pytest.raises(
        FileReadError, match="baseline column 'importe' has an invalid 'missing_pct'"
    ):
        load_baseline(baseline)
