"""CSV Unicode formatting controls are visible in Markdown but lossless in JSON."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from csv_quality_report.checks import CHECK_UNIQUE, CheckResult, code_span, escape_control_chars
from csv_quality_report.profile import ColumnProfile, Report
from csv_quality_report.render import _md_check_text, _md_literal, render_json, render_markdown

ROOT = Path(__file__).resolve().parents[1]
FORMAT_CHARS = (
    0x00AD,
    0x061C,
    0x200B,
    0x200E,
    0x200F,
    *range(0x202A, 0x202F),
    0x2028,
    0x2029,
    0x2060,
    *range(0x2066, 0x2070),
    0xFEFF,
)


@pytest.mark.parametrize("point", FORMAT_CHARS)
def test_invisible_format_characters_display_as_literal_ascii_markers(point: int) -> None:
    original = f"buyer{chr(point)}north"
    expected = f"buyer[U+{point:04X}]north"
    for rendered in (
        escape_control_chars(original),
        _md_literal(original),
        _md_check_text(original),
        code_span(original),
    ):
        assert chr(point) not in rendered
        assert expected in rendered


def test_rendered_reports_keep_original_json_identifiers_and_values() -> None:
    column = "order\u202eid"
    value = "An\u200bdes\u00adNorte\u2060\ufeff"
    report = Report(
        rows=2,
        duplicate_rows=1,
        truncated=False,
        columns=[
            ColumnProfile(
                name=column,
                type="string",
                missing=0,
                missing_pct=0.0,
                distinct=1,
                min=None,
                max=None,
                top_values=[(value, 2)],
            )
        ],
    )
    check = CheckResult(
        check=CHECK_UNIQUE,
        column=column,
        limit=0,
        value=1,
        passed=False,
        repeated=((value, 2),),
    )
    markdown = render_markdown(report, "file\u2028source.csv", checks=(check,))
    for point in (0x202E, 0x200B, 0x00AD, 0x2060, 0xFEFF, 0x2028):
        assert chr(point) not in markdown
        assert f"[U+{point:04X}]" in markdown
    parsed = json.loads(render_json(report, "file\u2028source.csv", checks=(check,)))
    assert parsed["source"] == "file\u2028source.csv"
    assert parsed["columns"][0]["name"] == column
    assert parsed["columns"][0]["top_values"][0]["value"] == value
    assert parsed["checks"][0]["repeated"] == {value: 2}


def test_multilingual_letters_and_script_joiners_remain_unchanged() -> None:
    original = "مشتري São Paulo 日本語 क्\u200dषि\u200c"
    assert escape_control_chars(original) == original
    assert _md_literal(original) == original
    assert _md_check_text(original) == original


def test_cli_preserves_json_and_sanitizes_markdown(tmp_path: Path) -> None:
    label = "An\u200bdes\u202eNorte\u2060\ufeff"
    file = tmp_path / "operators.csv"
    file.write_text("buyer\\n" + label + "\\n" + label + "\\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    args = [sys.executable, "-m", "csv_quality_report", str(file), "--unique", "buyer"]
    markdown = subprocess.run(
        args, cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )
    data = subprocess.run(
        [*args, "--format", "json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert markdown.returncode == 8, markdown.stderr
    assert data.returncode == 8, data.stderr
    for point in (0x200B, 0x202E, 0x2060, 0xFEFF):
        assert chr(point) not in markdown.stdout
        assert f"[U+{point:04X}]" in markdown.stdout
    parsed = json.loads(data.stdout)
    assert parsed["columns"][0]["top_values"][0]["value"] == label
    assert parsed["checks"][0]["repeated"] == {label: 2}
