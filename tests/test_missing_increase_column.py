"""Tests for ``--max-missing-increase-column NAME=PCT`` (issue #108)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report import Comparison
from csv_quality_report.checks import CHECK_MISSING_INCREASE, missing_increase_checks
from csv_quality_report.cli import main
from csv_quality_report.compare import MissingCount
from csv_quality_report.profile import profile_file
from csv_quality_report.render import render_json

WriteCsv = Callable[..., Path]
BEFORE = "id,peso,nota\n1,3,a\n2,4,b\n3,5,c\n4,6,d\n"
# peso: 0 of 4 missing -> 2 of 3 (+66.67 points); nota removed, moneda added.
AFTER = "id,peso,moneda\n1,,PYG\n2,,PYG\n3,5,PYG\n"
OPTION = "--max-missing-increase-column"


def write_baseline(write_csv: WriteCsv, tmp_path: Path, text: str = BEFORE) -> str:
    source = write_csv(text, "before.csv")
    path = tmp_path / "baseline.json"
    path.write_text(render_json(profile_file(source), str(source)), encoding="utf-8")
    return str(path)


def comparison(
    *counts: MissingCount, added: tuple[str, ...] = (), removed: tuple[str, ...] = ()
) -> Comparison:
    return Comparison("x.csv", 8, 9, added, removed, (), (), counts)


COUNTS = (
    MissingCount("a", 1, 4),  # 12.5% -> 44.44%: +31.94 points
    MissingCount("b", 2, 2),  # 25% -> 22.22%: fell
)


def summary(checks: list[Any]) -> list[tuple[str | None, float, float, bool]]:
    return [(c.column, c.limit, c.value, c.passed) for c in checks]


def test_column_limit_overrides_the_global_one() -> None:
    looser = missing_increase_checks(comparison(*COUNTS), 20, {"a": 40})
    assert summary(looser) == [("a", 40, 31.9444, True), ("b", 20, -2.7778, True)]
    tighter = missing_increase_checks(comparison(*COUNTS), 50, {"b": 0, "a": 30})
    assert summary(tighter) == [("a", 30, 31.9444, False), ("b", 0, -2.7778, True)]
    assert tighter[0].check == CHECK_MISSING_INCREASE
    assert tighter[0].describe() == (
        "column 'a' missing values rose 31.94 points since the baseline "
        "(12.5% -> 44.44%; limit 30 points)"
    )


def test_column_limits_without_a_global_limit_check_only_those_columns() -> None:
    assert summary(missing_increase_checks(comparison(*COUNTS), None, {"b": 1})) == [
        ("b", 1, -2.7778, True)
    ]
    assert missing_increase_checks(comparison(*COUNTS), None) == []
    assert missing_increase_checks(comparison(*COUNTS), None, {}) == []


def test_global_limit_alone_is_unchanged() -> None:
    assert summary(missing_increase_checks(comparison(*COUNTS), 20)) == [
        ("a", 20, 31.9444, False),
        ("b", 20, -2.7778, True),
    ]


def test_column_limit_is_exact() -> None:
    # 1 of 7 -> 9 of 14 rises exactly 50 points: equal to the limit, passes.
    counts = Comparison("x.csv", 7, 14, (), (), (), (), (MissingCount("a", 1, 9),))
    [check] = missing_increase_checks(counts, None, {"a": 50})
    assert (check.value, check.passed) == (50, True)
    [check] = missing_increase_checks(counts, 100, {"a": 49.9999})
    assert not check.passed


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("new", "the baseline has no column of that name"),
        ("old", "the file no longer has it"),
        ("typo", "neither the file nor the baseline has it"),
    ],
)
def test_named_column_that_cannot_be_compared_fails(name: str, reason: str) -> None:
    result = comparison(*COUNTS, added=("new",), removed=("old",))
    checks = missing_increase_checks(result, 20, {name: 5})
    # Compared columns come first, in the file's order; then the named ones.
    assert summary(checks) == [
        ("a", 20, 31.9444, False),
        ("b", 20, -2.7778, True),
        (name, 5, 0, False),
    ]
    assert (
        checks[-1].describe() == f"column '{name}' cannot be compared with the baseline ({reason})"
    )


def test_uncompared_names_keep_their_order() -> None:
    result = comparison(*COUNTS, added=("new",))
    checks = missing_increase_checks(result, None, {"typo": 1, "a": 40, "new": 2})
    assert [(c.column, c.limit, c.passed) for c in checks] == [
        ("a", 40, True),
        ("typo", 1, False),
        ("new", 2, False),
    ]


def test_column_limit_on_a_baseline_without_counts_fails() -> None:
    [check] = missing_increase_checks(comparison(MissingCount("a", None, 3)), None, {"a": 100})
    assert (check.column, check.limit, check.value, check.passed) == ("a", 100, 0, False)
    assert check.describe() == (
        "column 'a' cannot be compared with the baseline "
        "(the baseline has no 'missing' count for it)"
    )


def test_cli_column_limit_with_global_limit(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    args = [str(write_csv(AFTER)), "--baseline", baseline, "--format", "json"]
    # The global limit alone fails peso; a looser limit for peso lets it pass.
    assert main([*args, "--max-missing-increase", "10", OPTION, "peso=70"]) == 0
    checks = json.loads(capsys.readouterr().out)["checks"]
    assert checks == [
        {"check": "missing_increase", "column": "id", "limit": 10, "value": 0, "passed": True},
        {
            "check": "missing_increase",
            "column": "peso",
            "limit": 70,
            "value": 66.6667,
            "passed": True,
        },
    ]


def test_cli_column_limit_alone_fails_with_exit_code_8(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    today = str(write_csv(AFTER))
    assert main([today, "--baseline", baseline, OPTION, "peso=50"]) == 8
    captured = capsys.readouterr()
    assert captured.err == (
        "check failed: column 'peso' missing values rose 66.67 points since the baseline "
        "(0% -> 66.67%; limit 50 points)\n"
    )
    assert "## Checks: FAILED (1 of 1 failed)" in captured.out


def test_cli_last_limit_for_a_name_wins(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    args = [str(write_csv(AFTER)), "--baseline", baseline]
    assert main([*args, OPTION, "peso=70", OPTION, "peso=50"]) == 8
    capsys.readouterr()
    assert main([*args, OPTION, "peso=50", OPTION, "peso=70"]) == 0


def test_cli_names_may_contain_equals_signs(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path, "a=b,c\n1,2\n2,3\n")
    today = str(write_csv("a=b,c\n,2\n2,3\n"))
    assert main([today, "--baseline", baseline, OPTION, "a=b=49"]) == 8
    assert "column 'a=b' missing values rose 50 points" in capsys.readouterr().err
    assert main([today, "--baseline", baseline, OPTION, "a=b=50"]) == 0


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("moneda", "the baseline has no column of that name"),
        ("nota", "the file no longer has it"),
        ("Peso", "neither the file nor the baseline has it"),
    ],
)
def test_cli_named_column_that_cannot_be_compared(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
    reason: str,
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    today = str(write_csv(AFTER))
    assert main([today, "--baseline", baseline, OPTION, f"{name}=100"]) == 8
    assert capsys.readouterr().err == (
        f"check failed: column '{name}' cannot be compared with the baseline ({reason})\n"
    )


def test_cli_with_columns(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    args = [str(write_csv(AFTER)), "--baseline", baseline, "--columns", "peso", "--format", "json"]
    assert main([*args, OPTION, "peso=60"]) == 8
    checks = json.loads(capsys.readouterr().out)["checks"]
    assert [(c["column"], c["limit"], c["passed"]) for c in checks] == [("peso", 60, False)]
    with pytest.raises(SystemExit) as excinfo:
        main([*args, OPTION, "id=5"])
    assert excinfo.value.code == 2
    assert f"{OPTION} checks column 'id', which --columns leaves out" in capsys.readouterr().err


def test_cli_needs_a_baseline(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(BEFORE)), OPTION, "peso=5"])
    assert excinfo.value.code == 2
    assert f"{OPTION} needs --baseline" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("peso", f"invalid {OPTION} value: 'peso' (use NAME=PCT)"),
        ("=5", f"invalid {OPTION} value: '=5' (use NAME=PCT)"),
        ("peso=abc", "invalid percentage: 'abc'"),
        ("peso=101", "between 0 and 100"),
        ("peso=-1", "between 0 and 100"),
    ],
)
def test_cli_rejects_bad_values(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    value: str,
    message: str,
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(BEFORE)), "--baseline", baseline, OPTION, value])
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err


def test_max_missing_column_message_is_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main([str(write_csv(BEFORE)), "--max-missing-column", "peso"])
    assert "invalid --max-missing-column value: 'peso' (use NAME=PCT)" in capsys.readouterr().err
