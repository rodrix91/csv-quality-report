"""Markdown CSV renderers should show untrusted data literally without changing JSON."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from csv_quality_report.profile import ColumnProfile, Report
from csv_quality_report.render import render_json, render_markdown

ROOT = Path(__file__).resolve().parents[1]


def test_csv_labels_and_sample_values_do_not_create_links_or_html() -> None:
    name = "order|[line](https://example.invalid)"
    source = "[sales](https://example.invalid)<script>.csv"
    value = "[Open record](https://example.invalid)\n## APPROVED <img>&"
    column = ColumnProfile(
        name=name,
        type="string",
        missing=0,
        missing_pct=0.0,
        distinct=1,
        min=None,
        max=None,
        top_values=[(value, 1)],
    )
    report = Report(rows=1, duplicate_rows=0, truncated=False, columns=[column])
    markdown = render_markdown(report, source)
    assert r"\[sales\]\(https://example.invalid\)&lt;script&gt;.csv" in markdown
    assert r"order\|\[line\]\(https://example.invalid\)" in markdown
    assert r"\[Open record\]\(https://example.invalid\)" in markdown
    assert "&#10;## APPROVED &lt;img&gt;&amp;" in markdown
    assert "\n## APPROVED" not in markdown
    assert "[Open record](https://example.invalid)" not in markdown

    data = json.loads(render_json(report, source))
    assert data["source"] == source
    assert data["columns"][0]["name"] == name
    assert data["columns"][0]["top_values"][0]["value"] == value


def test_string_extrema_in_custom_report_cannot_split_markdown_table() -> None:
    column = ColumnProfile(
        name="id",
        type="string",
        missing=0,
        missing_pct=0.0,
        distinct=2,
        min="A|B",
        max="[Z](https://example.invalid)",
        top_values=[("A", 1), ("Z", 1)],
    )
    report = Report(rows=2, duplicate_rows=0, truncated=False, columns=[column])
    markdown = render_markdown(report, "source.csv")
    assert r" | A\|B | \[Z\]\(https://example.invalid\) | " in markdown
    data = json.loads(render_json(report, "source.csv"))
    assert data["columns"][0]["min"] == "A|B"
    assert data["columns"][0]["max"] == "[Z](https://example.invalid)"


def test_actual_csv_markdown_escape_preserves_json_values(tmp_path: Path) -> None:
    source = tmp_path / "records.csv"
    source.write_text(
        'buyer\n"[Invoice](https://example.invalid) | <b>Buyer</b>"\n',
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    args = [sys.executable, "-m", "csv_quality_report", str(source)]
    markdown = subprocess.run(
        args, cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )
    as_json = subprocess.run(
        [*args, "--format", "json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert markdown.returncode == 0, markdown.stderr
    assert as_json.returncode == 0, as_json.stderr
    assert r"\[Invoice\]\(https://example.invalid\) \| &lt;b&gt;Buyer&lt;/b&gt;" in markdown.stdout
    payload = json.loads(as_json.stdout)
    assert payload["columns"][0]["top_values"][0]["value"] == (
        "[Invoice](https://example.invalid) | <b>Buyer</b>"
    )
