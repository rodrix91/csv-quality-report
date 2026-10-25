"""Render a Report as Markdown or JSON text."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from typing import Any

from .checks import (
    CHECK_ALLOWED_VALUES,
    CHECK_BASELINE_AGE,
    CHECK_MAX_AFFIXES,
    CHECK_MAX_AGE,
    CHECK_PATTERN,
    CHECK_SCHEMA_CHANGE,
    CHECK_UNIQUE,
    CHECK_UNIQUE_KEY,
    CHECK_VALUE_RANGE,
    CheckResult,
    code_span,
)
from .compare import Comparison
from .profile import ColumnProfile, Report
from .reader import DEFAULT_ENCODING, DELIMITER_NAMES, delimiter_name


def _num(value: int | float | str | None) -> str:
    return "" if value is None else str(value)


def _md_code(text: str) -> str:
    """Fence arbitrary metadata as code, retaining the legacy escaped-pipe spelling."""
    return code_span(text.replace("|", r"\|"))


def _md_literal(text: str) -> str:
    """Render CSV text without creating Markdown links, HTML, or new table cells."""
    entities = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    translated = {ord(ch): "\\" + ch for ch in "\\`[]()|"}
    translated.update({ord("\r"): "&#13;", ord("\n"): "&#10;"})
    return entities.translate(translated)


def _md_check_text(text: str) -> str:
    """Keep arbitrary check names and examples from creating Markdown or HTML."""
    # Leave ordinary punctuation (underscores, arrows, parentheses) intact so
    # existing report prose remains stable; a literal [ or ` cannot open links
    # or inline code, and escaping < prevents HTML tags/autolinks.
    entities = text.replace("&", "&amp;").replace("<", "&lt;")
    escaped = {ord(ch): chr(92) + ch for ch in chr(92) + chr(96) + "[]|"}
    escaped.update({ord("\r"): "&#13;", ord("\n"): "&#10;"})
    return entities.translate(escaped)


def _md_check(check: CheckResult) -> str:
    """Escape CSV-derived check messages, retaining the regex code span."""
    text = _md_check_text(check.describe())
    if check.check == CHECK_PATTERN:
        # The regex uses an intentional code span: restore it unchanged after
        # escaping its surrounding column names and sample values.
        span = code_span(check.pattern)
        text = text.replace(_md_check_text(span), span, 1)
    return text


def _top(col: ColumnProfile) -> str:
    return ", ".join(f"{_md_literal(v)} ({n})" for v, n in col.top_values)


def _delimiter_line(report: Report) -> list[str]:
    """Markdown line naming the delimiter, only when it is not the default comma."""
    if report.delimiter == "," and not report.delimiter_detected and not report.sep_line:
        return []
    name = (
        delimiter_name(report.delimiter)
        if report.delimiter in DELIMITER_NAMES
        else _md_code(report.delimiter)
    )
    how = " (detected)" if report.delimiter_detected else ""
    if report.sep_line:
        how = " (declared by a sep= line)"
    return [f"- Delimiter: {name}{how}"]


def _skipped_line(report: Report) -> list[str]:
    """Markdown line counting the lines skipped before the header, only with ``--skip-lines``."""
    if not report.skipped_lines:
        return []
    return [f"- Skipped lines: {report.skipped_lines} (before the header)"]


def _footer_line(report: Report) -> list[str]:
    """Markdown line counting the records dropped after the data, only with ``--skip-footer``."""
    if not report.skipped_footer:
        return []
    records = "record" if report.skipped_footer == 1 else "records"
    return [f"- Skipped footer: {report.skipped_footer} {records} (after the data)"]


def _na_line(report: Report) -> list[str]:
    """Markdown line listing the extra missing-value tokens, only when there are some."""
    if not report.na_tokens:
        return []
    return ["- Also counted as missing: " + ", ".join(_md_code(t) for t in report.na_tokens)]


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
        lines.append(f"- {'FAIL' if not c.passed else 'pass'}: {_md_check(c)}")
    return lines


def _untrimmed_line(report: Report) -> list[str]:
    """Markdown line naming columns with untrimmed values, only when there are some."""
    found = [f"{_md_literal(c.name)} ({c.untrimmed})" for c in report.columns if c.untrimmed]
    return ["- Untrimmed values: " + ", ".join(found)] if found else []


def _untrimmed_columns_line(report: Report) -> list[str]:
    """Markdown line quoting header names with surrounding whitespace, when there are some."""
    if not report.untrimmed_columns:
        return []
    names = ", ".join(f'"{_md_literal(name)}"' for name in report.untrimmed_columns)
    return [f"- Column names with surrounding whitespace: {names}"]


def _type_hint_line(report: Report) -> list[str]:
    """Markdown line for string columns that mostly fit another type, when there are any."""
    parts = []
    for c in report.columns:
        if c.type_hint is not None:
            h = c.type_hint
            examples = ", ".join(f'"{_md_literal(v)}"' for v in h.examples)
            noun = "value" if h.nonconforming == 1 else "values"
            parts.append(
                f"{_md_literal(c.name)} is {h.type} except {h.nonconforming} {noun} ({examples})"
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
            found = ", ".join(f"{_md_code(a)} {n}" for a, n in c.affixes)
            parts.append(f"{_md_literal(c.name)} ({found})")
    return ["- Number affixes: " + "; ".join(parts)] if parts else []


def _bool_words_line(report: Report) -> list[str]:
    """Markdown line listing the extra boolean words, when some were given."""
    if not report.bool_words:
        return []
    pairs = ", ".join(f"{_md_code(t)}/{_md_code(f)}" for t, f in report.bool_words)
    return [f"- Boolean words (true/false): {pairs}"]


_DATE_ORDER_NAMES = {"dmy": "day/month/year", "mdy": "month/day/year", "ymd": "year/month/day"}


def _baseline_section(comparison: Comparison | None) -> list[str]:
    """Markdown section with the changes since a baseline report, when one was given."""
    if comparison is None:
        return []
    c = comparison
    lines = ["", "## Changes since baseline", ""]
    if c.baseline_source:
        lines.append(f"- Baseline: report of {_md_code(c.baseline_source)}")
    if c.baseline_generated_at is not None:
        lines.append(f"- Baseline generated: {_md_literal(c.baseline_generated_at)}")
    lines.append(f"- Rows: {c.rows_before} -> {c.rows_after}")
    if c.added_columns:
        lines.append("- Added columns: " + ", ".join(_md_literal(n) for n in c.added_columns))
    if c.removed_columns:
        lines.append("- Removed columns: " + ", ".join(_md_literal(n) for n in c.removed_columns))
    if c.type_changes:
        lines.append(
            "- Type changes: "
            + "; ".join(f"{_md_literal(t.column)} {t.before} -> {t.after}" for t in c.type_changes)
        )
    if c.missing_changes:
        lines.append(
            "- Missing values: "
            + "; ".join(
                f"{_md_literal(m.column)} {m.before_pct:.1f}% -> {m.after_pct:.1f}%"
                for m in c.missing_changes
            )
        )
    if not (c.added_columns or c.removed_columns or c.type_changes or c.missing_changes):
        lines.append("- No column changes")
    return lines


def _baseline_json(comparison: Comparison | None) -> dict[str, Any] | None:
    if comparison is None:
        return None
    c = comparison
    return {
        "source": c.baseline_source,
        # Only for a stamped baseline (--record-time), so other reports keep their bytes.
        **({} if c.baseline_generated_at is None else {"generated_at": c.baseline_generated_at}),
        "rows": {"before": c.rows_before, "after": c.rows_after},
        "added_columns": list(c.added_columns),
        "removed_columns": list(c.removed_columns),
        "type_changes": [
            {"column": t.column, "before": t.before, "after": t.after} for t in c.type_changes
        ],
        "missing_changes": [
            {"column": m.column, "before_pct": m.before_pct, "after_pct": m.after_pct}
            for m in c.missing_changes
        ],
    }


def render_markdown(
    report: Report,
    source: str,
    checks: Sequence[CheckResult] = (),
    comparison: Comparison | None = None,
) -> str:
    # The CLI uses <stdin> as a fixed sentinel, not a user-controlled path.
    display_source = source if source == "<stdin>" else _md_literal(source)
    lines = [
        f"# CSV quality report: {display_source}",
        "",
        f"- Rows analyzed: {report.rows}"
        + (" (stopped early by --max-rows)" if report.truncated else ""),
        f"- Columns: {len(report.columns)}"
        + (f" of {len(report.header)} (selected)" if report.selected_columns is not None else ""),
        *_delimiter_line(report),
        *_skipped_line(report),
        *_footer_line(report),
        *_na_line(report),
        *(["- Compression: gzip"] if report.compressed else []),
        *([f"- Encoding: {report.encoding}"] if report.encoding != DEFAULT_ENCODING else []),
        *_thousands_line(report),
        *([f"- Date order: {_DATE_ORDER_NAMES[report.date_order]}"] if report.date_order else []),
        *_bool_words_line(report),
        *(["- Accounting negatives: (5) and 5- read as -5"] if report.accounting_negatives else []),
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
            f"| {_md_literal(c.name)} | {c.type} | {c.missing} | {c.missing_pct:.1f} "
            f"| {c.distinct} | {_md_literal(_num(c.min))} | {_md_literal(_num(c.max))} "
            f"| {_md_literal(_num(c.mean))} | {_top(c)} |"
        )
    lines.extend(_baseline_section(comparison))
    lines.extend(_checks_section(checks))
    return "\n".join(lines) + "\n"


def _json_value(value: int | float | str | date | None) -> int | float | str | None:
    return value.isoformat() if isinstance(value, date) else value


def _unique_key_fields(check: CheckResult) -> dict[str, Any]:
    """JSON fields of a unique_key check: the key, the skipped rows and repeated keys."""
    return {
        "columns": list(check.key),
        "skipped": check.skipped,
        "repeated": [{"key": list(values), "rows": rows} for values, rows in check.repeated_keys],
    }


def _allowed_fields(check: CheckResult) -> dict[str, Any]:
    """JSON fields of a schema_change check with --allow-* options, each only when given."""
    fields: dict[str, Any] = {}
    if check.allowed_rules:
        fields["allowed_type_changes"] = [
            {"column": r.column, "before": r.before, "after": r.after} for r in check.allowed_rules
        ]
        fields["tolerated"] = [
            {"column": t.column, "before": t.before, "after": t.after} for t in check.tolerated
        ]
    if check.allowed_added:
        fields["allowed_added_columns"] = list(check.allowed_added)
        fields["tolerated_added_columns"] = list(check.tolerated_added)
    if check.allowed_removed:
        fields["allowed_removed_columns"] = list(check.allowed_removed)
        fields["tolerated_removed_columns"] = list(check.tolerated_removed)
    return fields


def _range_fields(check: CheckResult) -> dict[str, Any]:
    """JSON fields of a value_range check: the allowed range and the observed one."""
    (low, high), (first, last) = check.bounds, check.observed
    return {
        "range": {"min": _json_value(low), "max": _json_value(high)},
        "observed": {"min": first, "max": last},
    }


def render_json(
    report: Report,
    source: str,
    checks: Sequence[CheckResult] = (),
    comparison: Comparison | None = None,
    generated_at: str | None = None,
) -> str:
    """The report as JSON; ``generated_at`` (``--record-time``) adds that top-level key."""
    data: dict[str, Any] = {
        "source": source,
        **({} if generated_at is None else {"generated_at": generated_at}),
        "rows": report.rows,
        "truncated": report.truncated,
        "delimiter": report.delimiter,
        "delimiter_detected": report.delimiter_detected,
        "sep_line": report.sep_line,
        **({"skipped_lines": report.skipped_lines} if report.skipped_lines else {}),
        **({"skipped_footer": report.skipped_footer} if report.skipped_footer else {}),
        "na_tokens": list(report.na_tokens),
        "top_n": report.top_n,
        "compressed": report.compressed,
        "encoding": report.encoding,
        "thousands": report.thousands,
        "date_order": report.date_order,
        "bool_words": [list(pair) for pair in report.bool_words],
        "number_affixes": list(report.number_affixes),
        "accounting_negatives": report.accounting_negatives,
        "selected_columns": None
        if report.selected_columns is None
        else list(report.selected_columns),
        "header_columns": len(report.header),
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
        "baseline": _baseline_json(comparison),
        "checks": [
            {
                "check": c.check,
                "column": c.column,
                "limit": c.limit,
                "value": c.value,
                "passed": c.passed,
                **({"expected": c.expected, "actual": c.actual} if c.expected else {}),
                **({"found": dict(c.found)} if c.check == CHECK_MAX_AFFIXES else {}),
                **(_range_fields(c) if c.check == CHECK_VALUE_RANGE else {}),
                **({"repeated": dict(c.repeated)} if c.check == CHECK_UNIQUE else {}),
                **(_unique_key_fields(c) if c.check == CHECK_UNIQUE_KEY else {}),
                **(_allowed_fields(c) if c.check == CHECK_SCHEMA_CHANGE else {}),
                **({"generated_at": c.generated_at} if c.check == CHECK_BASELINE_AGE else {}),
                **({"newest": c.newest} if c.check == CHECK_MAX_AGE else {}),
                **(
                    {"allowed": list(c.allowed), "unexpected": dict(c.unexpected)}
                    if c.check == CHECK_ALLOWED_VALUES
                    else {}
                ),
                **(
                    {"pattern": c.pattern, "mismatched": dict(c.mismatched)}
                    if c.check == CHECK_PATTERN
                    else {}
                ),
            }
            for c in checks
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
