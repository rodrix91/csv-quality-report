"""Regression tests: JSON output must not overwrite inputs or baselines."""

from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report.cli import main
from csv_quality_report.errors import EXIT_IO
from csv_quality_report.profile import profile_file
from csv_quality_report.render import render_json

WriteCsv = Callable[..., Path]


@pytest.mark.parametrize("alias", ["direct", "normalized", "symlink", "hardlink"])
def test_json_output_never_overwrites_input(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    alias: str,
) -> None:
    source = write_csv("id,value\n1,first\n2,second\n", "source.csv")
    original = source.read_bytes()
    if alias == "direct":
        target = source
    elif alias == "normalized":
        (tmp_path / "nested").mkdir()
        target = tmp_path / "nested" / ".." / source.name
    elif alias == "symlink":
        target = tmp_path / "linked.csv"
        target.symlink_to(source)
    else:
        target = tmp_path / "linked.csv"
        target.hardlink_to(source)

    with pytest.raises(SystemExit) as excinfo:
        main([str(source), "--json-output", str(target)])

    assert excinfo.value.code == 2
    assert "--json-output" in capsys.readouterr().err
    assert source.read_bytes() == original


@pytest.mark.parametrize("alias", ["direct", "symlink", "hardlink"])
def test_json_output_never_overwrites_baseline(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    alias: str,
) -> None:
    source = write_csv("id,value\n1,first\n", "source.csv")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(render_json(profile_file(source), str(source)), encoding="utf-8")
    original = baseline.read_bytes()
    if alias == "direct":
        target = baseline
    elif alias == "symlink":
        target = tmp_path / "linked.json"
        target.symlink_to(baseline)
    else:
        target = tmp_path / "linked.json"
        target.hardlink_to(baseline)

    with pytest.raises(SystemExit) as excinfo:
        main([str(source), "--baseline", str(baseline), "--json-output", str(target)])

    assert excinfo.value.code == 2
    assert "--json-output" in capsys.readouterr().err
    assert baseline.read_bytes() == original


def test_distinct_json_output_is_still_written(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = write_csv("id\n1\n", "source.csv")
    target = tmp_path / "report.json"
    assert main([str(source), "--json-output", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["rows"] == 1
    assert capsys.readouterr().out.startswith("# CSV quality report:")


def test_stdin_input_does_not_protect_a_file_named_dash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # "-" means standard input, so a file called "-" in the working directory is
    # not the input and may receive the report.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "-").write_text("old\n", encoding="utf-8")
    buffer = io.BufferedReader(io.BytesIO(b"id\n1\n2\n"))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(buffer, encoding="utf-8"))
    assert main(["-", "--json-output", "-"]) == 0
    assert json.loads((tmp_path / "-").read_text(encoding="utf-8"))["rows"] == 2
    capsys.readouterr()


def test_missing_input_is_a_read_error_not_a_collision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "report.json"
    assert main([str(tmp_path / "missing.csv"), "--json-output", str(target)]) == EXIT_IO
    assert "--json-output" not in capsys.readouterr().err
    assert not target.exists()


def test_existing_unrelated_output_is_replaced(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = write_csv("id\n1\n", "source.csv")
    target = tmp_path / "report.json"
    target.write_text("stale", encoding="utf-8")
    assert main([str(source), "--json-output", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["rows"] == 1
    capsys.readouterr()
