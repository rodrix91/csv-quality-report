"""Render a Report as Markdown or JSON text."""

from __future__ import annotations

import json
from typing import Any

from .profile import ColumnProfile, Report
from .reader import DELIMITER_NAMES, delimiter_name


def _num(value: int | float | str | None) -> str:
    return "" if value is None else str(value)


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _top(col: ColumnProfile) -> str:
    return ", ".join(f"{_md_escape(v)} ({n})" for v, n in col.top_values)


def _delimiter_line(report: Report) -> list[str]:
    """Markdown line naming the delimiter, only when it is not the default comma."""
    if report.delimiter == "," and not report.delimiter_detected:
        return []
    name = (
        delimiter_name(report.delimiter)
        if report.delimiter in DELIMITER_NAMES
        else f"`{_md_escape(report.delimiter)}`"
    )
    return [f"- Delimiter: {name}" + (" (detected)" if report.delimiter_detected else "")]


def _na_line(report: Report) -> list[str]:
    """Markdown line listing the extra missing-value tokens, only when there are some."""
    if not report.na_tokens:
        return []
    return [
        "- Also counted as missing: " + ", ".join(f"`{_md_escape(t)}`" for t in report.na_tokens)
    ]


def render_markdown(report: Report, source: str) -> str:
    lines = [
        f"# CSV quality report: {_md_escape(source)}",
        "",
        f"- Rows analyzed: {report.rows}"
        + (" (stopped early by --max-rows)" if report.truncated else ""),
        f"- Columns: {len(report.columns)}",
        *_delimiter_line(report),
        *_na_line(report),
        f"- Duplicate rows: {report.duplicate_rows}",
        "",
        "| Column | Type | Missing | Missing % | Distinct | Min | Max | Top 3 values |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in report.columns:
        lines.append(
            f"| {_md_escape(c.name)} | {c.type} | {c.missing} | {c.missing_pct:.1f} "
            f"| {c.distinct} | {_num(c.min)} | {_num(c.max)} | {_top(c)} |"
        )
    return "\n".join(lines) + "\n"


def render_json(report: Report, source: str) -> str:
    data: dict[str, Any] = {
        "source": source,
        "rows": report.rows,
        "truncated": report.truncated,
        "delimiter": report.delimiter,
        "delimiter_detected": report.delimiter_detected,
        "na_tokens": list(report.na_tokens),
        "duplicate_rows": report.duplicate_rows,
        "columns": [
            {
                "name": c.name,
                "type": c.type,
                "missing": c.missing,
                "missing_pct": c.missing_pct,
                "distinct": c.distinct,
                "min": c.min,
                "max": c.max,
                "top_values": [{"value": v, "count": n} for v, n in c.top_values],
            }
            for c in report.columns
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
