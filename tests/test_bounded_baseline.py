"""Bound baseline JSON reads before decoding, without damaging prior reports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from csv_quality_report import compare as compare_module
from csv_quality_report.cli import main
from csv_quality_report.compare import load_baseline
from csv_quality_report.errors import FileReadError


def test_maximum_baseline_size_accepts_exact_limit_and_unicode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compare_module, "MAX_BASELINE_BYTES", 128)
    path = tmp_path / "baseline.json"
    document = json.dumps(
        {"rows": 0, "columns": [], "source": "Asunción"},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert len(document) < 128
    # Padding is legal JSON whitespace; the size limit applies to raw UTF-8
    # bytes, not characters or decoded string length.
    padded = document + b" " * (128 - len(document))
    path.write_bytes(padded)
    assert load_baseline(path)["source"] == "Asunción"
    path.write_bytes(padded + b" ")
    with pytest.raises(FileReadError, match="exceeds the 128-byte size limit"):
        load_baseline(path)


def test_oversized_baseline_fails_before_csv_read_and_preserves_prior_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(compare_module, "MAX_BASELINE_BYTES", 128)
    baseline = tmp_path / "oversized-history.json"
    baseline.write_bytes(b'{"rows":0,"columns":[]}' + b" " * 130)
    saved = tmp_path / "previous-report.json"
    saved.write_text('{"verified":true}\n', encoding="utf-8")
    missing_data = tmp_path / "no-such-dataset.csv"

    assert (
        main(
            [
                str(missing_data),
                "--baseline",
                str(baseline),
                "--format",
                "json",
                "--json-output",
                str(saved),
            ]
        )
        == 3
    )
    output = capsys.readouterr()
    assert "exceeds the 128-byte size limit" in output.err
    assert "no-such-dataset.csv" not in output.err
    assert output.out == ""
    assert saved.read_text(encoding="utf-8") == '{"verified":true}\n'


def test_invalid_utf8_under_limit_still_is_a_controlled_baseline_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compare_module, "MAX_BASELINE_BYTES", 128)
    path = tmp_path / "invalid.json"
    path.write_bytes(b'{"rows":0,"columns":[],"label":"\xff"}')
    with pytest.raises(FileReadError, match="is not a JSON report"):
        load_baseline(path)
