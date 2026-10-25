"""CSV-derived failed-check details must never become active Markdown markup."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from csv_quality_report.checks import CHECK_ALLOWED_VALUES, CHECK_PATTERN, CHECK_UNIQUE, CheckResult
from csv_quality_report.profile import ColumnProfile, Report
from csv_quality_report.render import render_json, render_markdown

ROOT = Path(__file__).resolve().parents[1]


def _report(name: str) -> Report:
    return Report(
        rows=2,
        duplicate_rows=1,
        truncated=False,
        columns=[
            ColumnProfile(
                name=name,
                type="string",
                missing=0,
                missing_pct=0.0,
                distinct=1,
                min=None,
                max=None,
                top_values=[],
            )
        ],
    )


def test_check_messages_escape_links_html_and_inline_backticks_without_changing_json() -> None:
    name = "ref[link](https://example.invalid)<img>"
    value = "[See record](https://example.invalid)<script>`fake`&"
    check = CheckResult(
        check=CHECK_ALLOWED_VALUES,
        column=name,
        limit=0,
        value=1,
        passed=False,
        allowed=("OK",),
        unexpected=((value, 1),),
    )
    markdown = render_markdown(_report(name), "input.csv", checks=(check,))
    assert r"ref\[link\](https://example.invalid)&lt;img&gt;" in markdown
    assert r"\[See record\](https://example.invalid)&lt;script&gt;\`fake\`&amp;" in markdown
    assert "[See record](https://example.invalid)" not in markdown
    assert "<script>" not in markdown
    data = json.loads(render_json(_report(name), "input.csv", checks=(check,)))
    assert data["checks"][0]["column"] == name
    assert data["checks"][0]["unexpected"] == {value: 1}


def test_pattern_code_span_remains_exact_but_csv_examples_are_escaped() -> None:
    pattern = r"[A-Z]|\d{2}"
    check = CheckResult(
        check=CHECK_PATTERN,
        column="code",
        limit=0,
        value=1,
        passed=False,
        pattern=pattern,
        mismatched=(("[open](https://example.invalid)<b>", 1),),
    )
    markdown = render_markdown(_report("code"), "input.csv", checks=(check,))
    assert r"pattern `[A-Z]|\d{2}`" in markdown
    assert r"\[open\](https://example.invalid)&lt;b&gt;" in markdown
    assert "[open](https://example.invalid)" not in markdown


def test_csv_backslash_cannot_cancel_markdown_bracket_escaping() -> None:
    value = r"\[open](https://example.invalid)"
    check = CheckResult(
        check=CHECK_UNIQUE,
        column="code",
        limit=0,
        value=1,
        passed=False,
        repeated=((value, 2),),
    )
    markdown = render_markdown(_report("code"), "input.csv", checks=(check,))
    assert r"\\\[open\](https://example.invalid)" in markdown
    assert json.loads(render_json(_report("code"), "input.csv", checks=(check,)))["checks"][0][
        "repeated"
    ] == {value: 2}


def test_cli_duplicate_check_escapes_csv_header_and_values(tmp_path: Path) -> None:
    name = "buyer[link](https://example.invalid)<b>"
    value = "[order](https://example.invalid)<img>"
    file = tmp_path / "records.csv"
    file.write_text(f"{name}\n{value}\n{value}\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    cmd = [sys.executable, "-m", "csv_quality_report", str(file), "--unique", name]
    markdown = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    as_json = subprocess.run(
        [*cmd, "--format", "json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert markdown.returncode == 8, markdown.stderr
    assert as_json.returncode == 8, as_json.stderr
    assert r"buyer\[link\](https://example.invalid)&lt;b&gt;" in markdown.stdout
    assert r"\[order\](https://example.invalid)&lt;img&gt;" in markdown.stdout
    assert "<img>" not in markdown.stdout
    data = json.loads(as_json.stdout)
    assert data["checks"][0]["check"] == CHECK_UNIQUE
    assert data["checks"][0]["column"] == name
    assert data["checks"][0]["repeated"] == {value: 2}
