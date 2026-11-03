"""Tests for the drift gate ``--max-mean-change`` (issue #260)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report import Comparison
from csv_quality_report.checks import (
    CHECK_MEAN_CHANGE,
    CheckResult,
    mean_change_checks,
)
from csv_quality_report.cli import main
from csv_quality_report.compare import ColumnMean, compare_reports
from csv_quality_report.profile import profile_file
from csv_quality_report.render import render_json

WriteCsv = Callable[..., Path]

YESTERDAY = "Fecha;Importe;Peso kg\n01/10/2026;1.234,50;12,5\n01/10/2026;980,00;3,25\n"
# Same amounts (one a little higher), weights now written in grams.
TODAY = "Fecha;Importe;Peso kg\n02/10/2026;1.240,50;12500,0\n02/10/2026;980,00;3250,0\n"
READ = ["--delimiter", ";", "--decimal-comma", "--thousands", "dot"]


def comparison(
    *means: ColumnMean, added: tuple[str, ...] = (), removed: tuple[str, ...] = ()
) -> Comparison:
    return Comparison("x.csv", 2, 2, added, removed, (), (), means=means)


def one(before: int | float | None, after: float | None, limit: float) -> CheckResult:
    [check] = mean_change_checks(
        comparison(ColumnMean("Importe", before, after)), {"Importe": limit}
    )
    return check


def write_baseline(write_csv: WriteCsv, tmp_path: Path, text: str = YESTERDAY) -> str:
    source = write_csv(text, "ayer.csv")
    report = profile_file(source, delimiter=";", decimal_comma=True, thousands=".")
    path = tmp_path / "baseline.json"
    path.write_text(render_json(report, str(source)), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize(
    ("before", "after", "limit", "value", "passed", "message"),
    [
        (100.0, 150.0, 50, 50, True, "mean rose 50% since the baseline (100 -> 150; limit 50%)"),
        (
            100.0,
            150.5,
            50,
            50.5,
            False,
            "mean rose 50.5% since the baseline (100 -> 150.5; limit 50%)",
        ),
        (
            100.0,
            49.5,
            50,
            50.5,
            False,
            "mean fell 50.5% since the baseline (100 -> 49.5; limit 50%)",
        ),
        (
            1234.5,
            1234500.0,
            100,
            99900,
            False,
            "mean rose 99900% since the baseline (1234.5 -> 1234500; limit 100%)",
        ),
        (
            1234.5,
            1.2345,
            50,
            99.9,
            False,
            "mean fell 99.9% since the baseline (1234.5 -> 1.2345; limit 50%)",
        ),
        (12.5, 12.5, 0, 0, True, "mean did not change since the baseline (12.5 -> 12.5; limit 0%)"),
        (0, 0.0, 0, 0, True, "mean did not change since the baseline (0 -> 0; limit 0%)"),
        # A negative mean (refunds, accounting negatives) changes relative to its size.
        (
            -200.0,
            -300.0,
            40,
            50,
            False,
            "mean fell 50% since the baseline (-200 -> -300; limit 40%)",
        ),
        (
            -200.0,
            200.0,
            250,
            200,
            True,
            "mean rose 200% since the baseline (-200 -> 200; limit 250%)",
        ),
        (4, 5.0, 25, 25, True, "mean rose 25% since the baseline (4 -> 5; limit 25%)"),
        (2e20, 1e20, 50, 50, True, "mean fell 50% since the baseline (2e+20 -> 1e+20; limit 50%)"),
        (
            1.5e-07,
            3e-07,
            100,
            100,
            True,
            "mean rose 100% since the baseline (1.5e-07 -> 3e-07; limit 100%)",
        ),
    ],
)
def test_mean_change_check(
    before: int | float,
    after: float,
    limit: float,
    value: float,
    passed: bool,
    message: str,
) -> None:
    check = one(before, after, limit)
    assert (check.check, check.column) == (CHECK_MEAN_CHANGE, "Importe")
    assert (check.limit, check.value, check.passed) == (limit, value, passed)
    assert (check.mean_before, check.mean_after) == (before, after)
    assert check.describe() == f"column 'Importe' {message}"


def test_the_change_and_the_limit_are_the_decimals_written() -> None:
    # In binary floats, (1.1 - 1.0) / 1.0 * 100 is 10.000000000000009 > 10.
    assert one(1.0, 1.1, 10).passed
    assert one(1.0, 1.1, 10).value == 10
    assert not one(1.0, 1.1, 9.999).passed
    # 0.1 + 0.2 is not 0.3 in floats; the means written are compared.
    assert one(0.3, 0.33, 10).passed


def test_a_mean_too_large_for_a_float_is_exact() -> None:
    huge = 10**400  # a JSON integer in a hand-written baseline
    check = one(huge, 1e300, 99)
    assert not check.passed and check.value == pytest.approx(100)
    assert check.describe().startswith("column 'Importe' mean fell 100% since the baseline (1000")


def test_tiny_change_is_not_shown_as_zero() -> None:
    check = one(123456.0, 123457.0, 0)
    assert not check.passed and 0 < check.value < 0.001
    # Means of hand-written baselines can be more precise than 6 digits; the
    # float after 10**20 is compared as the decimal it shows, 1.0000000000000002e+20.
    check = one(10**20, float(10**20 + 16384), 0)
    assert not check.passed and check.value == pytest.approx(2e-14)
    assert "mean rose 2e-14% since the baseline" in check.describe()


@pytest.mark.parametrize(
    ("before", "after", "reason"),
    [
        (None, 12.5, "the baseline has no mean for it"),
        (12.5, None, "the file has no mean for it"),
        (None, None, "the baseline has no mean for it"),
        (0, 1.5, "the baseline's mean is 0, so a relative change cannot be measured"),
        (0.0, -1.5, "the baseline's mean is 0, so a relative change cannot be measured"),
    ],
)
def test_a_mean_that_cannot_be_measured_fails(
    before: int | float | None, after: float | None, reason: str
) -> None:
    check = one(before, after, 1000)
    assert (check.passed, check.value, check.detail) == (False, 0, reason)
    assert (check.mean_before, check.mean_after) == (before, after)
    assert check.describe() == f"column 'Importe' cannot be compared with the baseline ({reason})"


def test_named_columns_follow_the_report_order_then_the_uncompared() -> None:
    means = (ColumnMean("a", 1.0, 1.0), ColumnMean("b", 2.0, 4.0), ColumnMean("c", 3.0, 3.0))
    checks = mean_change_checks(
        comparison(*means, added=("nuevo",), removed=("viejo",)),
        {"otra": 5, "viejo": 5, "b": 50, "nuevo": 5, "a": 0},
    )
    assert [(c.column, c.passed, c.detail) for c in checks] == [
        ("a", True, "fell"),
        ("b", False, "rose"),
        ("otra", False, "neither the file nor the baseline has it"),
        ("viejo", False, "the file no longer has it"),
        ("nuevo", False, "the baseline has no column of that name"),
    ]
    assert all(c.mean_before is None and c.mean_after is None for c in checks[2:])
    assert mean_change_checks(comparison(*means), {}) == []


def test_comparison_keeps_both_means_as_written(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("id,monto,nota\n1,10.5,x\n2,20,y\n"))
    baseline: dict[str, Any] = {
        "rows": 2,
        "columns": [
            {"name": "id", "type": "int", "missing_pct": 0.0, "mean": 10**400},
            {"name": "monto", "type": "float", "missing_pct": 0.0, "mean": 15.25},
            {"name": "nota", "type": "string", "missing_pct": 0.0, "mean": None},
            {"name": "viejo", "type": "float", "missing_pct": 0.0, "mean": 3.0},
        ],
    }
    assert compare_reports(baseline, report).means == (
        ColumnMean("id", 10**400, 1.5),
        ColumnMean("monto", 15.25, 15.25),
        ColumnMean("nota", None, None),
    )


@pytest.mark.parametrize("mean", [True, "12.5", float("nan"), float("inf"), -float("inf"), [1]])
def test_a_baseline_mean_that_is_not_a_finite_number_is_no_mean(
    mean: object, write_csv: WriteCsv
) -> None:
    report = profile_file(write_csv("monto\n1\n"))
    baseline = {
        "rows": 1,
        "columns": [{"name": "monto", "type": "int", "missing_pct": 0, "mean": mean}],
    }
    assert compare_reports(baseline, report).means == (ColumnMean("monto", None, 1.0),)


def test_a_baseline_without_means_has_no_mean(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("monto\n1\n"))
    baseline = {"rows": 1, "columns": [{"name": "monto", "type": "int", "missing_pct": 0}]}
    [check] = mean_change_checks(compare_reports(baseline, report), {"monto": 5})
    assert check.detail == "the baseline has no mean for it"


def test_cli_weights_written_in_grams_fail(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    today = str(write_csv(TODAY, "hoy.csv"))
    args = [today, *READ, "--baseline", baseline]
    assert main([*args, "--max-mean-change", "Importe=5", "--max-mean-change", "Peso kg=50"]) == 8
    captured = capsys.readouterr()
    assert captured.err == (
        "check failed: column 'Peso kg' mean rose 99900% since the baseline "
        "(7.875 -> 7875; limit 50%)\n"
    )
    assert (
        "- pass: column 'Importe' mean rose 0.2709% since the baseline (1107.25 -> 1110.25; "
        "limit 5%)\n- FAIL: column 'Peso kg' mean rose 99900%" in captured.out
    )
    # The schema, the types, the rows and the missing values did not change.
    gates = ["--fail-on-schema-change", "--max-row-drop", "0", "--max-row-growth", "0"]
    assert main([*args, *gates, "--max-missing-increase", "0"]) == 0


def test_cli_json_and_the_last_limit_for_a_name_wins(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    args = [str(write_csv(TODAY, "hoy.csv")), *READ, "--baseline", baseline, "--format", "json"]
    limits = ["--max-mean-change", "Peso kg=5", "--max-mean-change", "Peso kg=100000"]
    assert main([*args, *limits, "--max-mean-change", "Fecha=5"]) == 8
    assert json.loads(capsys.readouterr().out)["checks"] == [
        {
            "check": "mean_change",
            "column": "Fecha",
            "limit": 5.0,
            "value": 0,
            "passed": False,
            "before": None,
            "after": None,
        },
        {
            "check": "mean_change",
            "column": "Peso kg",
            "limit": 100000.0,
            "value": 99900.0,
            "passed": True,
            "before": 7.875,
            "after": 7875.0,
        },
    ]


def test_cli_without_the_option_has_no_mean_change_check(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    args = [str(write_csv(TODAY, "hoy.csv")), *READ, "--baseline", baseline, "--format", "json"]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["checks"] == []


def test_mean_change_needs_a_baseline(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(TODAY)), *READ, "--max-mean-change", "Importe=5"])
    assert excinfo.value.code == 2
    assert "--max-mean-change needs --baseline" in capsys.readouterr().err


def test_mean_change_column_left_out_by_columns(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    args = [str(write_csv(TODAY, "hoy.csv")), *READ, "--baseline", baseline, "--columns", "Fecha"]
    with pytest.raises(SystemExit) as excinfo:
        main([*args, "--max-mean-change", "Importe=5"])
    assert excinfo.value.code == 2
    assert "--max-mean-change checks column 'Importe', which --columns leaves out" in (
        capsys.readouterr().err
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (
            "Importe",
            "invalid --max-mean-change value: 'Importe' (use NAME=PCT, such as Importe=50)",
        ),
        ("=5", "invalid --max-mean-change value: '=5' (use NAME=PCT, such as Importe=50)"),
        ("Importe=", "invalid percentage: ''"),
        ("Importe=abc", "invalid percentage: 'abc'"),
        ("Importe=-1", "must be a finite number of 0 or more"),
        ("Importe=nan", "must be a finite number of 0 or more"),
        ("Importe=inf", "must be a finite number of 0 or more"),
        ("Importe=1e400", "must be a finite number of 0 or more"),
    ],
)
def test_mean_change_rejects_bad_values(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    value: str,
    message: str,
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                str(write_csv(TODAY, "hoy.csv")),
                *READ,
                "--baseline",
                baseline,
                f"--max-mean-change={value}",
            ]
        )
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err


def test_a_name_may_contain_equals(write_csv: WriteCsv, tmp_path: Path) -> None:
    text = "a=b\n10\n20\n"
    baseline = tmp_path / "baseline.json"
    source = write_csv(text, "ayer.csv")
    baseline.write_text(render_json(profile_file(source), str(source)), encoding="utf-8")
    today = str(write_csv("a=b\n10\n21\n", "hoy.csv"))
    assert main([today, "--baseline", str(baseline), "--max-mean-change", "a=b=3.3334"]) == 0
    assert main([today, "--baseline", str(baseline), "--max-mean-change", "a=b=3.3"]) == 8
