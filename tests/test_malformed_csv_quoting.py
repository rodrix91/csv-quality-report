"""Malformed quoted fields must fail closed in the streaming CSV quality gate."""

from __future__ import annotations

import gzip
import io
import sys
from pathlib import Path

import pytest

from csv_quality_report.cli import main
from csv_quality_report.errors import RaggedRowError
from csv_quality_report.profile import profile_file
from csv_quality_report.reader import read_table


@pytest.mark.parametrize(
    "data",
    [
        'id,buyer\n1,"unterminated\n',
        'id,buyer\n1,"closed"garbage\n',
        'id,buyer\n1,"multiline\nstill open\n',
    ],
)
def test_malformed_quoted_cells_are_rejected_not_profiled(
    tmp_path: Path, data: str
) -> None:
    path = tmp_path / "malformed.csv"
    path.write_bytes(data.encode("utf-8"))
    with pytest.raises(RaggedRowError, match="malformed CSV near line"):
        profile_file(path)
    with pytest.raises(RaggedRowError, match="malformed CSV near line"):
        read_table(path)


@pytest.mark.parametrize("ending", ["\n", "\r", "\r\n"])
def test_malformed_quotes_fail_for_all_physical_line_endings(
    tmp_path: Path, ending: str
) -> None:
    path = tmp_path / "line-endings.csv"
    path.write_bytes(ending.join(["id,buyer", '1,"unfinished', ""]).encode())
    with pytest.raises(RaggedRowError, match="malformed CSV near line"):
        profile_file(path)


def test_gzip_with_unclosed_quote_fails_instead_of_returning_a_report(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.csv.gz"
    path.write_bytes(gzip.compress(b'id;buyer\r1;"unfinished\r'))
    with pytest.raises(RaggedRowError, match="malformed CSV near line"):
        profile_file(path, delimiter=";")


def test_stdin_quoted_error_exits_without_closing_the_caller_stream(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    buffer = io.BufferedReader(io.BytesIO(b'id,buyer\n1,"unfinished\n'))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(buffer, encoding="utf-8"))
    assert main(["-", "--format", "json"]) == 6
    output = capsys.readouterr()
    assert output.out == ""
    assert "malformed CSV near line" in output.err
    assert not buffer.closed


def test_malformed_quote_fails_without_replacing_verified_json_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "broken.csv"
    source.write_bytes(b'id,buyer\n1,"unfinished\n')
    output_path = tmp_path / "verified.json"
    previous = '{"previous":"verified"}\n'
    output_path.write_text(previous, encoding="utf-8")
    assert main([str(source), "--json-output", str(output_path)]) == 6
    output = capsys.readouterr()
    assert output.out == ""
    assert "malformed CSV near line" in output.err
    assert output_path.read_text(encoding="utf-8") == previous


def test_auto_delimiter_does_not_mask_malformed_quoted_csv(
    tmp_path: Path,
) -> None:
    path = tmp_path / "auto.csv"
    path.write_bytes(b'id;buyer\n1;"unfinished\n')
    with pytest.raises(RaggedRowError, match="malformed CSV near line"):
        profile_file(path, delimiter="auto")


def test_valid_multiline_quoted_fields_remain_lossless(tmp_path: Path) -> None:
    path = tmp_path / "valid.csv"
    path.write_bytes(b'id,buyer\r\n1,"North\r\nSouth"\r\n2,Andes\r\n')
    data = read_table(path)
    assert data.header == ["id", "buyer"]
    assert data.rows == [["1", "North\r\nSouth"], ["2", "Andes"]]
    assert profile_file(path).rows == 2
