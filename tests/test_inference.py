from __future__ import annotations

import pytest

from csv_quality_report.inference import infer_type


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["1", "-2", "+3", "0"], "int"),
        (["1", "2.5", "3e2", ".5"], "float"),
        (["true", "False", "TRUE"], "bool"),
        (["2024-01-31", "1999-12-01"], "date"),
        (["2024-02-30"], "string"),  # impossible date
        (["20240131"], "int"),  # no ISO dashes -> plain integer
        (["1", "x"], "string"),
        (["nan", "inf"], "string"),
        (["0", "1"], "int"),  # 0/1 are ints, not bools
        ([], "string"),
    ],
)
def test_infer_type(values: list[str], expected: str) -> None:
    assert infer_type(values) == expected
