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
        '{"rows":1,"columns":[],' + json.dumps(key) + ":1," + json.dumps(key) + ":2}",
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
                "columns": [{"name": long_name, "type": "string", "missing_pct": 101}],
            }
        ),
        encoding="utf-8",
    )
    previous = tmp_path / "verified.json"
    previous.write_text('{"verified":true}\n', encoding="utf-8")
    assert (
        main(
            [
                str(tmp_path / "missing.csv"),
                "--baseline",
                str(baseline),
                "--format",
                "json",
                "--json-output",
                str(previous),
            ]
        )
        == 3
    )
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
        '{"rows":1,"columns":[{"name":"importe","type":"float","missing_pct":105}]}',
        encoding="utf-8",
    )
    with pytest.raises(
        FileReadError, match="baseline column 'importe' has an invalid 'missing_pct'"
    ):
        load_baseline(baseline)


@pytest.mark.parametrize("control", ["\x1b", "\n", "\r", "\t", "\u202e", "\ud800"])
def test_escaped_baseline_labels_are_bounded_after_repr_expansion(control: str) -> None:
    from csv_quality_report.compare import _baseline_error_label

    name = control * 120
    diagnostic = _baseline_error_label(name)
    assert len(diagnostic) <= 175
    assert diagnostic.endswith(" [truncated]")
    assert control not in diagnostic
    assert "..." in diagnostic


def test_short_escaped_baseline_names_keep_prior_diagnostics() -> None:
    from csv_quality_report.compare import _baseline_error_label

    assert _baseline_error_label("Tarija") == "'Tarija'"
    assert _baseline_error_label("a\nb") == repr("a\nb")
    assert _baseline_error_label("\x1b" * 3) == repr("\x1b" * 3)
    assert _baseline_error_label("x" * 121) == repr("x" * 120) + " [truncated]"


def test_duplicate_json_key_with_many_controls_has_bounded_log_output(tmp_path: Path) -> None:
    name = "\x1b" * 120 + "-private-trailing-token"
    baseline = tmp_path / "duplicate-control-name.json"
    baseline.write_text(
        '{"rows":1,"columns":[],' + json.dumps(name) + ":1," + json.dumps(name) + ":2}",
        encoding="utf-8",
    )
    with pytest.raises(FileReadError, match="duplicate baseline JSON key") as error:
        load_baseline(baseline)
    diagnostic = str(error.value)
    # Pytest's absolute temporary directory has platform-specific length.
    # Bound the diagnostic itself, excluding the expected filename prefix.
    assert len(diagnostic) - len(str(baseline)) < 260
    assert "[truncated]" in diagnostic
    assert "\x1b" not in diagnostic
    assert "-private-trailing-token" not in diagnostic


def test_column_error_with_control_heavy_name_stays_one_log_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    name = "\x1b" * 120 + "private-trailing-token"
    baseline = tmp_path / "historic.json"
    baseline.write_text(
        json.dumps({
            "rows": 1,
            "columns": [{"name": name, "type": "int", "missing_pct": 101}],
        }),
        encoding="utf-8",
    )
    saved = tmp_path / "existing.json"
    saved.write_text('{"verified":true}\n', encoding="utf-8")
    exit_code = main([
        str(tmp_path / "missing.csv"),
        "--baseline", str(baseline),
        "--json-output", str(saved),
    ])
    captured = capsys.readouterr()
    assert exit_code == 3
    assert captured.out == ""
    assert "invalid 'missing_pct'" in captured.err
    assert "[truncated]" in captured.err
    assert "\x1b" not in captured.err
    assert "private-trailing-token" not in captured.err
    assert captured.err.count("\n") == 1
    assert len(captured.err) < 450
    assert saved.read_text(encoding="utf-8") == '{"verified":true}\n'
