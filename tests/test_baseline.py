"""Tests for ``--baseline`` and ``--fail-on-schema-change`` (issue #91)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report import Comparison, compare_reports
from csv_quality_report.checks import CHECK_SCHEMA_CHANGE, schema_change_check
from csv_quality_report.cli import main
from csv_quality_report.compare import MissingChange, TypeChange, load_baseline
from csv_quality_report.errors import FileReadError
from csv_quality_report.profile import profile_file
from csv_quality_report.render import render_json, render_markdown

WriteCsv = Callable[..., Path]
BEFORE = "id,monto,peso,nota\n1,10.5,3,a\n2,7,4,b\n3,8,5,c\n4,9,6,d\n"
AFTER = "id,monto,peso,moneda\n1,10.5,,PYG\n2,consultar,,PYG\n3,8,5,PYG\n"


def baseline_of(write_csv: WriteCsv, text: str = BEFORE, **options: Any) -> dict[str, Any]:
    path = write_csv(text, "before.csv")
    report = profile_file(path, **options)
    data: dict[str, Any] = json.loads(render_json(report, str(path)))
    return data


def test_changes_are_found(write_csv: WriteCsv) -> None:
    comparison = compare_reports(baseline_of(write_csv), profile_file(write_csv(AFTER)))
    assert comparison.rows_before == 4 and comparison.rows_after == 3
    assert comparison.added_columns == ("moneda",)
    assert comparison.removed_columns == ("nota",)
    assert comparison.type_changes == (TypeChange("monto", "float", "string"),)
    assert comparison.missing_changes == (MissingChange("peso", 0.0, 66.7),)
    assert comparison.schema_changes == 3
    assert comparison.baseline_source.endswith("before.csv")


def test_same_file_has_no_changes(write_csv: WriteCsv) -> None:
    comparison = compare_reports(baseline_of(write_csv), profile_file(write_csv(BEFORE)))
    assert (comparison.schema_changes, comparison.missing_changes) == (0, ())
    assert (comparison.added_columns, comparison.removed_columns) == ((), ())


def test_reading_options_matter(write_csv: WriteCsv) -> None:
    # A baseline made with --decimal-comma against a run without it: a type change.
    text = "monto;n\n10,5;1\n7,25;2\n"
    baseline = baseline_of(write_csv, text, delimiter=";", decimal_comma=True)
    comparison = compare_reports(baseline, profile_file(write_csv(text), delimiter=";"))
    assert comparison.type_changes == (TypeChange("monto", "float", "string"),)


def test_selected_columns_compare_only_those(write_csv: WriteCsv) -> None:
    after = profile_file(write_csv(AFTER), columns=["peso", "id"])
    comparison = compare_reports(baseline_of(write_csv), after)
    assert (comparison.added_columns, comparison.removed_columns) == ((), ())
    assert comparison.missing_changes == (MissingChange("peso", 0.0, 66.7),)
    # A selected column that the baseline did not have is added.
    with_new = profile_file(write_csv(AFTER), columns=["moneda"])
    assert compare_reports(baseline_of(write_csv), with_new).added_columns == ("moneda",)


def test_schema_change_check() -> None:
    comparison = Comparison(
        baseline_source="x.csv",
        rows_before=1,
        rows_after=1,
        added_columns=("a",),
        removed_columns=("b", "c"),
        type_changes=(TypeChange("d", "int", "string"),),
        missing_changes=(MissingChange("e", 0.0, 50.0),),
    )
    check = schema_change_check(comparison)
    assert (check.check, check.value, check.limit, check.passed) == (
        CHECK_SCHEMA_CHANGE,
        4,
        0,
        False,
    )
    assert check.describe() == (
        "4 schema changes since the baseline: added 'a'; removed 'b', 'c'; 'd' int -> string"
    )
    one = Comparison("x.csv", 1, 1, (), (), (TypeChange("d", "int", "float"),), ())
    assert schema_change_check(one).describe() == (
        "1 schema change since the baseline: 'd' int -> float"
    )
    clean = schema_change_check(Comparison("x.csv", 1, 2, (), (), (), (MissingChange("e", 0, 1),)))
    assert clean.passed  # missing-value and row changes are informational
    assert clean.describe() == "no columns added, removed or retyped since the baseline"


def write_baseline(write_csv: WriteCsv, tmp_path: Path) -> Path:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(baseline_of(write_csv)), encoding="utf-8")
    return path


def test_cli_reports_and_fails(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    after = str(write_csv(AFTER))
    assert main([after, "--baseline", str(baseline)]) == 0  # informational by default
    out = capsys.readouterr().out
    assert out.endswith(
        "\n## Changes since baseline\n\n"
        f"- Baseline: report of `{tmp_path / 'before.csv'}`\n"
        "- Rows: 4 -> 3\n"
        "- Added columns: moneda\n"
        "- Removed columns: nota\n"
        "- Type changes: monto float -> string\n"
        "- Missing values: peso 0.0% -> 66.7%\n"
    )
    assert main([after, "--baseline", str(baseline), "--fail-on-schema-change"]) == 8
    assert capsys.readouterr().err == (
        "check failed: 3 schema changes since the baseline: "
        "added 'moneda'; removed 'nota'; 'monto' float -> string\n"
    )


def test_cli_json(write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    args = [str(write_csv(AFTER)), "--baseline", str(baseline), "--format", "json"]
    assert main([*args, "--fail-on-schema-change"]) == 8
    data = json.loads(capsys.readouterr().out)
    assert data["baseline"] == {
        "source": str(tmp_path / "before.csv"),
        "rows": {"before": 4, "after": 3},
        "added_columns": ["moneda"],
        "removed_columns": ["nota"],
        "type_changes": [{"column": "monto", "before": "float", "after": "string"}],
        "missing_changes": [{"column": "peso", "before_pct": 0.0, "after_pct": 66.7}],
    }
    assert data["checks"] == [
        {"check": "schema_change", "column": None, "limit": 0, "value": 3, "passed": False}
    ]


def test_no_column_changes_line(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    assert main([str(write_csv(BEFORE)), "--baseline", str(baseline)]) == 0
    assert "- Rows: 4 -> 4\n- No column changes\n" in capsys.readouterr().out


def test_without_baseline_nothing_changes(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(BEFORE))
    assert main([path, "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["baseline"] is None
    assert main([path]) == 0
    assert "Changes since baseline" not in capsys.readouterr().out


def test_fail_on_schema_change_needs_a_baseline(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(BEFORE)), "--fail-on-schema-change"])
    assert excinfo.value.code == 2
    assert "--fail-on-schema-change needs --baseline" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "cannot read baseline"),
        ("not json", "is not a JSON report (Expecting value"),
        (b"\xff\xfe", "is not a JSON report ("),
        ("[1, 2]", "is not a csv-quality-report JSON report"),
        ('{"rows": "8", "columns": []}', "(it has no 'rows' count and 'columns' list)"),
        ('{"rows": true, "columns": []}', "(it has no 'rows' count and 'columns' list)"),
        ('{"rows": 1, "columns": [{"name": "a"}]}', "a column has no 'name', 'type'"),
        (
            '{"rows": 1, "columns": [{"name": "a", "type": "int", "missing_pct": true}]}',
            "a column has no 'name', 'type'",
        ),
    ],
)
def test_unusable_baselines_are_read_errors(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    content: str | bytes | None,
    message: str,
) -> None:
    path = tmp_path / "baseline.json"
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif content is not None:
        path.write_text(content, encoding="utf-8")
    with pytest.raises(FileReadError, match=message.replace("(", r"\(").replace(")", r"\)")):
        load_baseline(path)
    assert main([str(write_csv(BEFORE)), "--baseline", str(path)]) == 3
    assert message in capsys.readouterr().err


def test_baseline_is_read_before_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Both are missing: the baseline error comes first, without profiling.
    code = main([str(tmp_path / "missing.csv"), "--baseline", str(tmp_path / "missing.json")])
    assert code == 3
    assert "cannot read baseline" in capsys.readouterr().err


def test_compare_reports_rejects_other_json(write_csv: WriteCsv) -> None:
    with pytest.raises(ValueError, match="no 'rows' count"):
        compare_reports({"columns": []}, profile_file(write_csv(BEFORE)))


def test_render_functions_accept_a_comparison(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(AFTER))
    comparison = compare_reports(baseline_of(write_csv), report)
    assert "## Changes since baseline" in render_markdown(report, "x", (), comparison)
    assert json.loads(render_json(report, "x", (), comparison))["baseline"]["rows"]["after"] == 3


def test_baseline_without_source_omits_the_line(write_csv: WriteCsv) -> None:
    baseline = baseline_of(write_csv)
    del baseline["source"]
    report = profile_file(write_csv(BEFORE))
    comparison = compare_reports(baseline, report)
    text = render_markdown(report, "x", (), comparison)
    assert "- Baseline:" not in text and "- Rows: 4 -> 4\n" in text


@pytest.mark.parametrize(
    "comparison",
    [
        Comparison("x.csv", 1, 1, ("new",), (), (), ()),
        Comparison("x.csv", 1, 1, (), ("gone",), (), ()),
    ],
)
def test_added_or_removed_columns_alone_fail(comparison: Comparison) -> None:
    check = schema_change_check(comparison)
    assert (check.passed, check.value) == (False, 1)
