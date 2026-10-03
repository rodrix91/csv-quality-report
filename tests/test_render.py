"""Direct tests of the renderers, independent of CSV parsing."""

from __future__ import annotations

import json
import math

import pytest

from csv_quality_report.profile import ColumnProfile, Report
from csv_quality_report.render import render_json


def _report(low: float, high: float) -> Report:
    column = ColumnProfile(
        name="x",
        type="float",
        missing=0,
        missing_pct=0.0,
        distinct=2,
        min=low,
        max=high,
        top_values=[("1", 1)],
    )
    return Report(rows=2, duplicate_rows=0, truncated=False, columns=[column])


@pytest.mark.parametrize(
    ("low", "high"),
    [(math.inf, 1.0), (1.0, -math.inf), (math.nan, 1.0)],
)
def test_render_json_refuses_non_finite_numbers(low: float, high: float) -> None:
    """NaN/Infinity are not standard JSON: rendering must fail, not emit them."""
    with pytest.raises(ValueError, match="Out of range float values"):
        render_json(_report(low, high), "x.csv")


def test_render_json_finite_numbers_are_strict_json() -> None:
    out = render_json(_report(0.5, 2.5), "x.csv")

    def reject(constant: str) -> None:
        raise AssertionError(f"non-standard JSON constant: {constant}")

    data = json.loads(out, parse_constant=reject)
    assert (data["columns"][0]["min"], data["columns"][0]["max"]) == (0.5, 2.5)
