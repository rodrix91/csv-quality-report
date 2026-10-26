"""CSV and check metadata cannot insert invisible controls into Markdown output."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from csv_quality_report.checks import CHECK_UNIQUE, CheckResult, code_span
from csv_quality_report.profile import ColumnProfile, Report
from csv_quality_report.render import _md_check_text, _md_literal, render_json, render_markdown

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("codepoint", [*range(9), *range(10, 32), *range(127, 160)])
def test_all_c0_del_and_c1_controls_are_escaped_in_markdown(codepoint: int) -> None:
    value = f"buyer{chr(codepoint)}north"
    literal = _md_literal(value)
    check_text = _md_check_text(value)
    for encoded in (literal, check_text):
        assert f"buyer&#{codepoint};north" in encoded
        assert chr(codepoint) not in encoded

    span = code_span(value)
    if codepoint in (10, 13):
        # The existing one-line code-span convention replaces line breaks with spaces.
        assert span == "`buyer north`"
    else:
        assert f"buyer&#{codepoint};north" in span
        assert chr(codepoint) not in span


def test_check_messages_and_column_values_preserve_original_json() -> None:
    name = "supplier\x1b\x00\x9b\x7f"
    value = "Andes\x08\x07\x1f\x9f"
    col = ColumnProfile(
        name=name,
        type="string",
        missing=0,
        missing_pct=0.0,
        distinct=1,
        min=None,
        max=None,
        top_values=[(value, 2)],
    )
    report = Report(rows=2, duplicate_rows=1, truncated=False, columns=[col])
    check = CheckResult(
        check=CHECK_UNIQUE,
        column=name,
        limit=0,
        value=1,
        passed=False,
        repeated=((value, 2),),
    )
    markdown = render_markdown(report, "source\x1b.csv", checks=(check,))
    for character in ("\x00", "\x07", "\x08", "\x1b", "\x1f", "\x7f", "\x9b", "\x9f"):
        assert character not in markdown
    for codepoint in (0, 7, 8, 27, 31, 127, 155, 159):
        assert f"&#{codepoint};" in markdown

    payload = json.loads(render_json(report, "source\x1b.csv", checks=(check,)))
    assert payload["source"] == "source\x1b.csv"
    assert payload["columns"][0]["name"] == name
    assert payload["columns"][0]["top_values"][0]["value"] == value
    assert payload["checks"][0]["repeated"] == {value: 2}


def test_cli_renders_literal_csv_controls_without_changing_json(tmp_path: Path) -> None:
    value = "Andes\x1b[31m\x08\x7f\x9b\tNorte"
    path = tmp_path / "suppliers.csv"
    path.write_text("buyer\n" + value + "\n", encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHONIOENCODING": "utf-8",
    }
    command = [sys.executable, "-m", "csv_quality_report", str(path)]
    markdown = subprocess.run(
        command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", check=False
    )
    json_result = subprocess.run(
        [*command, "--format", "json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert markdown.returncode == 0, markdown.stderr
    assert json_result.returncode == 0, json_result.stderr
    for character in ("\x1b", "\x08", "\x7f", "\x9b"):
        assert character not in markdown.stdout
    for codepoint in (27, 8, 127, 155):
        assert f"&#{codepoint};" in markdown.stdout
    # Tabs in imported data are intentionally kept as literal whitespace.
    assert "\t" in markdown.stdout
    payload = json.loads(json_result.stdout)
    assert payload["columns"][0]["top_values"][0]["value"] == value
