"""Failed CSV quality gates cannot forge terminal or CI log output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from csv_quality_report.cli import _safe_failed_check_message, main
from csv_quality_report.errors import EXIT_CHECKS


@pytest.mark.parametrize(
    ("character", "visible"),
    [
        (chr(10), r"\n"),
        (chr(13), r"\r"),
        (chr(9), r"\t"),
        (chr(0), r"\x00"),
        (chr(27), r"\x1b"),
        (chr(127), r"\x7f"),
        (chr(155), r"\x9b"),
        (chr(0x202E), r"\u202e"),
        (chr(0x2028), r"\u2028"),
        (chr(0x2029), r"\u2029"),
        (chr(0x200B), r"\u200b"),
        (chr(0xD800), r"\ud800"),
        (chr(0xE0001), r"\U000e0001"),
    ],
)
def test_failed_check_messages_escape_control_and_format_characters(
    character: str, visible: str
) -> None:
    text = "Tarija " + character + " Jujuy"
    safe = _safe_failed_check_message(text)
    assert safe == "Tarija " + visible + " Jujuy"
    assert character not in safe
    assert "\n" not in safe
    assert "\r" not in safe


def test_failed_check_message_bounds_escaped_output_and_preserves_normal_text() -> None:
    assert _safe_failed_check_message("") == ""
    assert _safe_failed_check_message("cliente Ñandú, 50% incompleto") == (
        "cliente Ñandú, 50% incompleto"
    )
    large = "x" * 10_000 + "hidden-private-tail"
    safe = _safe_failed_check_message(large)
    assert len(safe) <= 4110
    assert safe.endswith(" [truncated]")
    assert "hidden-private-tail" not in safe
    # Escapes expand the output too: the limit is on the *rendered* line.
    escaped = _safe_failed_check_message(chr(27) * 10_000)
    assert len(escaped) <= 4110
    assert escaped.endswith(" [truncated]")
    assert chr(27) not in escaped


def test_failed_missing_gate_keeps_stderr_safe_and_json_source_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    column = "buyer" + chr(27) + chr(0x9B) + chr(0x202E) + chr(0x200B)
    csv = tmp_path / "control-headers.csv"
    csv.write_text(column + '\nfilled\n""\n', encoding="utf-8")
    assert main([str(csv), "--max-missing", "0", "--format", "json"]) == EXIT_CHECKS
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["columns"][0]["name"] == column
    assert report["checks"][0]["passed"] is False
    assert captured.err.count("\n") == 1
    for character in (chr(27), chr(0x9B), chr(0x202E), chr(0x200B)):
        assert character not in captured.err
    for marker in (r"\x1b", r"\x9b", r"\u202e", r"\u200b"):
        assert marker in captured.err
    assert "check failed: column 'buyer" in captured.err


def test_duplicate_value_gate_escapes_raw_csv_control_bytes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    value = "north" + chr(27) + "[31m" + chr(0x2029) + "south"
    csv = tmp_path / "control-values.csv"
    csv.write_text("supplier\n" + value + "\n" + value + "\n", encoding="utf-8")
    assert main([str(csv), "--unique", "supplier", "--format", "json"]) == EXIT_CHECKS
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["columns"][0]["top_values"][0]["value"] == value
    assert chr(27) not in captured.err
    assert chr(0x2029) not in captured.err
    assert r"\x1b[31m" in captured.err
    assert r"\u2029" in captured.err
    assert captured.err.count("\n") == 1
