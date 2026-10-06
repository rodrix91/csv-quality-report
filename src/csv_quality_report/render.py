"""Render a Report as Markdown or JSON text."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from .checks import CHECK_MAX_AFFIXES, CheckResult
from .profile import ColumnProfile, Report
from .reader import DEFAULT_ENCODING, DELIMITER_NAMES, delimiter_name


def _num(value: int | float | str | None) -> str:
    return "" if value is None else str(value)


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _top(col: ColumnProfile) -> str:
    return ", ".join(f"{_md_escape(v)} ({n})" for v, n in col.top_values)


def _delimiter_line(report: Report) -> list[str]:
    """Markdown line naming the delimiter, only when it is not the default comma."""
    if report.delimiter == "," and not report.delimiter_detected and not report.sep_line:
        return []
    name = (
        delimiter_name(report.delimiter)
        if report.delimiter in DELIMITER_NAMES
        else f"`{_md_escape(report.delimiter)}`"
    )
    how = " (detected)" if report.delimiter_detected else ""
    if report.sep_line:
        how = " (declared by a sep= line)"
    return [f"- Delimiter: {name}{how}"]


def _na_line(report: Report) -> list[str]:
    """Markdown line listing the extra missing-value tokens, only when there are some."""
    if not report.na_tokens:
        return []
    return [
        "- Also counted as missing: " + ", ".join(f"`{_md_escape(t)}`" for t in report.na_tokens)
    ]


def _checks_section(checks: Sequence[CheckResult]) -> list[str]:
    """Markdown section with each requested check, only when checks were requested."""
    if not checks:
        return []
    failed = sum(not c.passed for c in checks)
    lines = [
        "",
        f"## Checks: {'FAILED' if failed else 'passed'} ({failed} of {len(checks)} failed)",
        "",
    ]
    for c in checks:
        lines.append(f"- {'FAIL' if not c.passed else 'pass'}: {_md_escape(c.describe())}")
    return lines


def _untrimmed_line(report: Report) -> list[str]:
    """Markdown line naming columns with untrimmed values, only when there are some."""
    found = [f"{_md_escape(c.name)} ({c.untrimmed})" for c in report.columns if c.untrimmed]
    return ["- Untrimmed values: " + ", ".join(found)] if found else []


def _untrimmed_columns_line(report: Report) -> list[str]:
    """Markdown line quoting header names with surrounding whitespace, when there are some."""
    if not report.untrimmed_columns:
        return []
    names = ", ".join(f'"{_md_escape(name)}"' for name in report.untrimmed_columns)
    return [f"- Column names with surrounding whitespace: {names}"]


def _type_hint_line(report: Report) -> list[str]:
    """Markdown line for string columns that mostly fit another type, when there are any."""
    parts = []
    for c in report.columns:
        if c.type_hint is not None:
            h = c.type_hint
            examples = ", ".join(f'"{_md_escape(v)}"' for v in h.examples)
            noun = "value" if h.nonconforming == 1 else "values"
            parts.append(
                f"{_md_escape(c.name)} is {h.type} except {h.nonconforming} {noun} ({examples})"
            )
    return ["- Mostly typed: " + "; ".join(parts)] if parts else []


_THOUSANDS_NAMES = {".": "dot", ",": "comma", " ": "space"}


def _thousands_line(report: Report) -> list[str]:
    """Markdown line naming the thousands separator, when one was given."""
    if report.thousands is None:
        return []
    return [f"- Thousands separator: {_THOUSANDS_NAMES[report.thousands]}"]


def _affixes_line(report: Report) -> list[str]:
    """Markdown line with the number affixes found per column, when there are any."""
    parts = []
    for c in report.columns:
        if c.affixes:
            found = ", ".join(f"`{_md_escape(a)}` {n}" for a, n in c.affixes)
            parts.append(f"{_md_escape(c.name)} ({found})")
    return ["- Number affixes: " + "; ".join(parts)] if parts else []


def _bool_words_line(report: Report) -> list[str]:
    """Markdown line listing the extra boolean words, when some were given."""
    if not report.bool_words:
        return []
    pairs = ", ".join(f"`{_md_escape(t)}`/`{_md_escape(f)}`" for t, f in report.bool_words)
    return [f"- Boolean words (true/false): {pairs}"]


_DATE_ORDER_NAMES = {"dmy": "day/month/year", "mdy": "month/day/year", "ymd": "year/month/day"}


def render_markdown(report: Report, source: str, checks: Sequence[CheckResult] = ()) -> str:
    lines = [
        f"# CSV quality report: {_md_escape(source)}",
        "",
        f"- Rows analyzed: {report.rows}"
        + (" (stopped early by --max-rows)" if report.truncated else ""),
        f"- Columns: {len(report.columns)}",
        *_delimiter_line(report),
        *_na_line(report),
        *(["- Compression: gzip"] if report.compressed else []),
        *([f"- Encoding: {report.encoding}"] if report.encoding != DEFAULT_ENCODING else []),
        *_thousands_line(report),
        *([f"- Date order: {_DATE_ORDER_NAMES[report.date_order]}"] if report.date_order else []),
        *_bool_words_line(report),
        f"- Duplicate rows: {report.duplicate_rows}",
        *_untrimmed_line(report),
        *_untrimmed_columns_line(report),
        *_type_hint_line(report),
        *_affixes_line(report),
        "",
        "| Column | Type | Missing | Missing % | Distinct | Min | Max | Mean "
        f"| Top {report.top_n} values |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in report.columns:
        lines.append(
            f"| {_md_escape(c.name)} | {c.type} | {c.missing} | {c.missing_pct:.1f} "
            f"| {c.distinct} | {_num(c.min)} | {_num(c.max)} | {_num(c.mean)} | {_top(c)} |"
        )
    lines.extend(_checks_section(checks))
    return "\n".join(lines) + "\n"


def render_json(report: Report, source: str, checks: Sequence[CheckResult] = ()) -> str:
    data: dict[str, Any] = {
        "source": source,
        "rows": report.rows,
        "truncated": report.truncated,
        "delimiter": report.delimiter,
        "delimiter_detected": report.delimiter_detected,
        "sep_line": report.sep_line,
        "na_tokens": list(report.na_tokens),
        "top_n": report.top_n,
        "compressed": report.compressed,
        "encoding": report.encoding,
        "thousands": report.thousands,
        "date_order": report.date_order,
        "bool_words": [list(pair) for pair in report.bool_words],
        "number_affixes": list(report.number_affixes),
        "duplicate_rows": report.duplicate_rows,
        "untrimmed_columns": list(report.untrimmed_columns),
        "columns": [
            {
                "name": c.name,
                "type": c.type,
                "type_hint": None
                if c.type_hint is None
                else {
                    "type": c.type_hint.type,
                    "conforming_pct": c.type_hint.conforming_pct,
                    "nonconforming": c.type_hint.nonconforming,
                    "examples": list(c.type_hint.examples),
                },
                "missing": c.missing,
                "missing_pct": c.missing_pct,
                "distinct": c.distinct,
                "min": c.min,
                "max": c.max,
                "mean": c.mean,
                "min_length": c.min_length,
                "max_length": c.max_length,
                "top_values": [{"value": v, "count": n} for v, n in c.top_values],
                "untrimmed": c.untrimmed,
                "affixes": dict(c.affixes),
            }
            for c in report.columns
        ],
        "checks": [
            {
                "check": c.check,
                "column": c.column,
                "limit": c.limit,
                "value": c.value,
                "passed": c.passed,
                **({"expected": c.expected, "actual": c.actual} if c.expected else {}),
                **({"found": dict(c.found)} if c.check == CHECK_MAX_AFFIXES else {}),
            }
            for c in checks
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
