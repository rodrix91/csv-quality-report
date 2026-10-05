"""Optional quality gates evaluated on a finished ``Report``.

Thresholds turn the report into a pass/fail signal for pipelines: the CLI
still prints the full report, lists failed checks on stderr and exits with
``EXIT_CHECKS`` when at least one check fails.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .profile import Report

CHECK_MAX_MISSING = "max_missing"
CHECK_MAX_DUPLICATES = "max_duplicates"
CHECK_REQUIRED_COLUMN = "required_column"
_MAX_LISTED = 10  # columns named in a "missing column" message


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one threshold on one column (or on the whole file)."""

    check: str
    column: str | None  # None for file-level checks
    limit: float
    value: float
    passed: bool
    detail: str = ""  # extra context for messages (not part of the JSON output)

    def describe(self) -> str:
        """One-line, human-readable explanation used on stderr and in Markdown."""
        if self.check == CHECK_MAX_MISSING:
            return (
                f"column '{self.column}' has {_fmt(self.value)}% missing values "
                f"(limit {_fmt(self.limit)}%)"
            )
        if self.check == CHECK_REQUIRED_COLUMN:
            if self.passed:
                return f"required column '{self.column}' is present"
            return f"required column '{self.column}' is missing (columns: {self.detail})"
        return f"{_fmt(self.value)} duplicate rows (limit {_fmt(self.limit)})"


def _fmt(number: float) -> str:
    """Print 10.0 as 10 and keep real decimals (12.5, 33.3333)."""
    return f"{number:g}" if number == int(number) else f"{number:.4g}"


def evaluate(
    report: Report,
    max_missing: float | None = None,
    max_duplicates: int | None = None,
    required_columns: Iterable[str] = (),
) -> list[CheckResult]:
    """Evaluate the requested thresholds; a value equal to its limit passes.

    ``required_columns`` are matched exactly (case-sensitive) against the
    reported header, after duplicate-name suffixes; each one gives a check
    with ``value`` 1 when present and 0 when missing (``limit`` is 1).

    The missing percentage is computed exactly from the counts, not from the
    one-decimal ``missing_pct`` shown in the report, so rounding can never
    hide a value just above the limit.
    """
    results: list[CheckResult] = []
    if max_missing is not None:
        for col in report.columns:
            pct = 100.0 * col.missing / report.rows if report.rows else 0.0
            results.append(
                CheckResult(
                    check=CHECK_MAX_MISSING,
                    column=col.name,
                    limit=max_missing,
                    value=round(pct, 4),
                    passed=pct <= max_missing,
                )
            )
    if max_duplicates is not None:
        results.append(
            CheckResult(
                check=CHECK_MAX_DUPLICATES,
                column=None,
                limit=max_duplicates,
                value=report.duplicate_rows,
                passed=report.duplicate_rows <= max_duplicates,
            )
        )
    header = [col.name for col in report.columns]
    present = set(header)
    listed = ", ".join(header[:_MAX_LISTED]) + (", ..." if len(header) > _MAX_LISTED else "")
    for name in dict.fromkeys(required_columns):
        found = name in present
        results.append(
            CheckResult(
                check=CHECK_REQUIRED_COLUMN,
                column=name,
                limit=1,
                value=1 if found else 0,
                passed=found,
                detail="" if found else listed,
            )
        )
    return results
