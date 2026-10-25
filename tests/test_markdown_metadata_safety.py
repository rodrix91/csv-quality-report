"""Untrusted CSV metadata must not become active Markdown in job summaries."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from csv_quality_report.checks import code_span
from csv_quality_report.compare import Comparison, MissingChange, TypeChange
from csv_quality_report.profile import ColumnProfile, Report, TypeHint
from csv_quality_report.render import render_json, render_markdown

ROOT = Path(__file__).resolve().parents[1]


def _unsafe_report() -> Report:
    raw_name = " buyer[Open](https://example.invalid)<img> "
    raw_code = "NA`[Open](https://example.invalid)<img>\n## forged"
    return Report(
        rows=2,
        duplicate_rows=0,
        truncated=False,
        columns=[
            ColumnProfile(
                name=raw_name,
                type="string",
                missing=0,
                missing_pct=0.0,
                distinct=2,
                min=None,
                max=None,
                top_values=[("safe", 2)],
                untrimmed=1,
                type_hint=TypeHint(
                    type="int",
                    conforming_pct=90.0,
                    nonconforming=1,
                    examples=("[View](https://example.invalid)<script>\n## injected",),
                ),
                affixes=((raw_code, 1),),
            )
        ],
        na_tokens=(raw_code,),
        untrimmed_columns=(raw_name,),
        bool_words=((raw_code, "false"),),
    )


def test_metadata_code_spans_contain_backticks_html_and_newlines_safely() -> None:
    report = _unsafe_report()
    raw_code = report.na_tokens[0]
    markdown = render_markdown(report, "input.csv")
    literal = code_span(raw_code)
    assert markdown.count(literal) == 3  # NA token, affix and true boolean word
    assert literal.startswith("``")  # a single backtick cannot terminate the span
    assert "\n## forged" not in markdown
    assert "\n## injected" not in markdown
    assert r"buyer\[Open\]\(https://example.invalid\)&lt;img&gt;" in markdown
    assert r"\[View\]\(https://example.invalid\)&lt;script&gt;&#10;## injected" in markdown
    assert (
        "[Open](https://example.invalid)<img>"
        not in markdown.split("- Untrimmed values:", 1)[1].split("\n", 1)[0]
    )
    assert "&#10;## forged" not in markdown  # code spans replace line breaks with spaces

    encoded = json.loads(render_json(report, "input.csv"))
    assert encoded["na_tokens"] == [raw_code]
    assert encoded["bool_words"] == [[raw_code, "false"]]
    assert encoded["columns"][0]["name"] == report.columns[0].name


def test_baseline_free_text_and_inline_source_remain_escaped_without_json_loss() -> None:
    name = "[Open](https://example.invalid)<svg>"
    baseline = Comparison(
        baseline_source="prior`[Open](https://example.invalid)<script>.json",
        baseline_generated_at="yesterday\n## APPROVED <img>",
        rows_before=1,
        rows_after=2,
        added_columns=(name,),
        removed_columns=(name,),
        type_changes=(TypeChange(name, "int", "string"),),
        missing_changes=(MissingChange(name, 0.0, 20.0),),
    )
    report = _unsafe_report()
    markdown = render_markdown(report, "input.csv", comparison=baseline)
    assert f"- Baseline: report of {code_span(baseline.baseline_source)}" in markdown
    assert "- Baseline generated: yesterday&#10;## APPROVED &lt;img&gt;" in markdown
    assert "\n## APPROVED" not in markdown
    assert r"\[Open\]\(https://example.invalid\)&lt;svg&gt;" in markdown
    assert "[Open](https://example.invalid)<svg>" not in markdown
    data = json.loads(render_json(report, "input.csv", comparison=baseline))
    assert data["baseline"]["source"] == baseline.baseline_source
    assert data["baseline"]["generated_at"] == baseline.baseline_generated_at
    assert data["baseline"]["added_columns"] == [name]


def test_cli_untrusted_na_token_cannot_end_markdown_code_span(tmp_path: Path) -> None:
    path = tmp_path / "simple.csv"
    path.write_text("id\nA\nB\n", encoding="utf-8")
    token = "NA`[Open](https://example.invalid)<script>"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    command = [sys.executable, "-m", "csv_quality_report", str(path), "--na", token]
    markdown = subprocess.run(
        command, cwd=ROOT, env=env, text=True, capture_output=True, check=False
    )
    json_result = subprocess.run(
        [*command, "--format", "json"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert markdown.returncode == 0, markdown.stderr
    assert json_result.returncode == 0, json_result.stderr
    assert f"- Also counted as missing: {code_span(token)}" in markdown.stdout
    assert json.loads(json_result.stdout)["na_tokens"] == [token]
