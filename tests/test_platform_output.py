"""Output is the same on every platform: UTF-8, ``\\n`` line endings, ``/`` in paths (#120).

The Windows CI job found that a redirected stdout used the ANSI code page and
CRLF, and that paths were reported with backslashes. These tests pin the
portable behavior; on Linux they simulate the Windows streams.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from csv_quality_report.cli import main
from csv_quality_report.reader import display_name

WriteCsv = Callable[..., Path]
# Names outside cp1252 (the Windows code page that crashed) and inside it.
DATA = "ciudad,n\n東京,1\nSofía,2\nСофия,3\n"


def test_redirected_output_is_utf8_whatever_the_stream_encoding(
    write_csv: WriteCsv, cli_env: dict[str, str]
) -> None:
    path = write_csv(DATA)
    proc = subprocess.run(
        [sys.executable, "-m", "csv_quality_report", str(path), "--require-columns", "東京x"],
        env={**cli_env, "PYTHONIOENCODING": "cp1252"},
        capture_output=True,
    )
    assert proc.returncode == 8, proc.stderr
    out, err = proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")
    assert "東京 (1), Sofía (1), София (1)" in out
    assert "check failed: required column '東京x' is missing" in err
    assert b"\r\n" not in proc.stdout + proc.stderr


def test_main_writes_utf8_and_lf_to_a_windows_like_stream(
    write_csv: WriteCsv, monkeypatch: pytest.MonkeyPatch
) -> None:
    buffer = io.BytesIO()
    # cp1252 with CRLF translation is what a redirected stdout gets on Windows.
    stream = io.TextIOWrapper(buffer, encoding="cp1252", newline="\r\n", write_through=True)
    monkeypatch.setattr(sys, "stdout", stream)
    assert main([str(write_csv(DATA)), "--format", "json"]) == 0
    raw = buffer.getvalue()
    assert b"\r\n" not in raw
    report = json.loads(raw.decode("utf-8"))
    assert [v["value"] for v in report["columns"][0]["top_values"]] == ["東京", "Sofía", "София"]


def test_main_leaves_a_plain_text_stream_alone(
    write_csv: WriteCsv, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    assert main([str(write_csv(DATA))]) == 0
    assert "| ciudad | string |" in stream.getvalue()


def test_json_output_file_is_utf8_with_lf(write_csv: WriteCsv, tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    assert main([str(write_csv(DATA)), "--json-output", str(target)]) == 0
    raw = target.read_bytes()
    assert b"\r\n" not in raw and "東京".encode() in raw


@pytest.mark.parametrize(
    "path",
    [PureWindowsPath("tests\\corpus\\data.csv"), PurePosixPath("tests/corpus/data.csv")],
)
def test_paths_are_reported_with_forward_slashes(path: PureWindowsPath | PurePosixPath) -> None:
    assert display_name(path) == "tests/corpus/data.csv"


def test_stdin_keeps_its_name_on_every_platform() -> None:
    assert display_name(PureWindowsPath("-")) == "<stdin>"
