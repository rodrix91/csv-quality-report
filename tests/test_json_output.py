"""Tests for ``--json-output FILE`` (issue #30)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report.cli import main
from csv_quality_report.errors import EXIT_CHECKS, EXIT_WRITE

WriteCsv = Callable[..., Path]
DATA = "a,b\n1,x\n,y\n1,x\n"


def test_writes_json_and_keeps_markdown_on_stdout(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, out = write_csv(DATA), tmp_path / "report.json"
    assert main([str(path), "--json-output", str(out)]) == 0
    stdout = capsys.readouterr().out
    assert stdout.startswith("# CSV quality report:")
    # The file is exactly what --format json prints.
    assert main([str(path), "--format", "json"]) == 0
    assert out.read_text(encoding="utf-8") == capsys.readouterr().out


def test_file_is_written_when_a_gate_fails(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "report.json"
    code = main([str(write_csv(DATA)), "--max-duplicates=0", "--json-output", str(out)])
    assert code == EXIT_CHECKS
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["checks"][0]["passed"] is False
    assert "check failed:" in capsys.readouterr().err


def test_non_ascii_text_is_written_as_utf8(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "r.json"
    assert main([str(write_csv("ciudad\nSão Paulo\nAsunción\n")), "--json-output", str(out)]) == 0
    assert "Asunción" in out.read_bytes().decode("utf-8")


def test_unwritable_target_has_its_own_exit_code(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "missing-dir" / "report.json"
    assert main([str(write_csv(DATA)), "--json-output", str(target)]) == EXIT_WRITE == 9
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(f"error: cannot write '{target}': ")


def test_reading_errors_write_no_file(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "report.json"
    assert main([str(write_csv("a,b\n1\n")), "--json-output", str(out)]) == 6
    assert not out.exists()


def test_existing_file_is_replaced(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "report.json"
    out.write_text("old content that is longer than the new report " * 200, encoding="utf-8")
    assert main([str(write_csv(DATA)), "--json-output", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["rows"] == 3
