"""Tests for ``--allow-type-change`` on the ``--fail-on-schema-change`` gate (issue #127)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report import Comparison
from csv_quality_report.checks import (
    CHECK_SCHEMA_CHANGE,
    COLUMN_TYPES,
    TypeChangeRule,
    schema_change_check,
)
from csv_quality_report.cli import main
from csv_quality_report.compare import TypeChange
from csv_quality_report.profile import profile_file
from csv_quality_report.render import render_json, render_markdown

WriteCsv = Callable[..., Path]
ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
# Whole units and dates in the baseline; decimals, times and a text code later.
BEFORE = "id,qty,day,code\n1,3,2026-10-05,10\n2,4,2026-10-06,11\n"
AFTER = "id,qty,day,code\n1,3.5,2026-10-12 08:00,10\n2,4,2026-10-13 09:30,A-11\n"


def changes(*items: tuple[str, str, str]) -> Comparison:
    """A comparison with only these (column, before, after) type changes."""
    return Comparison("x.csv", 2, 2, (), (), tuple(TypeChange(*item) for item in items), ())


def write_baseline(write_csv: WriteCsv, tmp_path: Path, text: str = BEFORE) -> str:
    path = write_csv(text, "before.csv")
    target = tmp_path / "baseline.json"
    target.write_text(render_json(profile_file(path), str(path)), encoding="utf-8")
    return str(target)


def run(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *options: str,
    text: str = AFTER,
) -> tuple[int, dict[str, Any], str]:
    """Run the CLI on ``text`` against the BEFORE baseline; (exit code, JSON, stderr)."""
    baseline = write_baseline(write_csv, tmp_path)
    after = str(write_csv(text, "after.csv"))
    capsys.readouterr()
    code = main([after, "--format", "json", "--baseline", baseline, *options])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


# --- the rule -------------------------------------------------------------


def test_rule_matches_its_exact_pair_and_column() -> None:
    anywhere = TypeChangeRule("int", "float")
    only_qty = TypeChangeRule("int", "float", "qty")
    assert anywhere.matches(TypeChange("qty", "int", "float"))
    assert anywhere.matches(TypeChange("other", "int", "float"))
    assert only_qty.matches(TypeChange("qty", "int", "float"))
    assert not only_qty.matches(TypeChange("other", "int", "float"))
    # Exact pairs: neither the reverse nor another target is implied.
    assert not anywhere.matches(TypeChange("qty", "float", "int"))
    assert not anywhere.matches(TypeChange("qty", "int", "string"))
    assert (str(anywhere), str(only_qty)) == ("int:float", "qty=int:float")


@pytest.mark.parametrize(
    ("before", "after", "column", "message"),
    [
        ("integer", "float", None, "unknown column type 'integer'; use one of int, float"),
        ("int", "text", None, "unknown column type 'text'"),
        ("int", "int", None, "int:int is not a type change"),
        ("int", "float", "", "needs a column name or None"),
    ],
)
def test_rule_rejects_what_cannot_be_a_type_change(
    before: str, after: str, column: str | None, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        TypeChangeRule(before, after, column)


def test_every_pair_of_distinct_types_is_a_valid_rule() -> None:
    pairs = [(a, b) for a in COLUMN_TYPES for b in COLUMN_TYPES if a != b]
    assert len(pairs) == 30
    for before, after in pairs:
        assert TypeChangeRule(before, after).matches(TypeChange("c", before, after))


# --- the check ------------------------------------------------------------


def test_without_rules_the_check_is_unchanged() -> None:
    comparison = Comparison(
        "x.csv", 2, 2, ("new",), ("old",), (TypeChange("qty", "int", "float"),), ()
    )
    check = schema_change_check(comparison)
    assert check == schema_change_check(comparison, ())
    assert (check.value, check.passed, check.allowed_rules, check.tolerated) == (3, False, (), ())
    assert check.describe() == (
        "3 schema changes since the baseline: added 'new'; removed 'old'; 'qty' int -> float"
    )


def test_allowed_changes_are_not_counted_and_are_listed() -> None:
    comparison = changes(
        ("code", "int", "string"), ("qty", "int", "float"), ("day", "date", "datetime")
    )
    rules = [TypeChangeRule("int", "float", "qty"), TypeChangeRule("date", "datetime")]
    check = schema_change_check(comparison, rules)
    assert (check.check, check.value, check.limit, check.passed) == (
        CHECK_SCHEMA_CHANGE,
        1,
        0,
        False,
    )
    assert check.tolerated == (
        TypeChange("qty", "int", "float"),
        TypeChange("day", "date", "datetime"),
    )
    assert check.allowed_rules == tuple(rules)
    assert check.describe() == (
        "1 schema change since the baseline: 'code' int -> string "
        "(allowed: 'qty' int -> float; 'day' date -> datetime)"
    )


def test_a_check_with_only_allowed_changes_passes_and_says_what_it_allowed() -> None:
    check = schema_change_check(
        changes(("qty", "int", "float"), ("price", "int", "float")),
        [TypeChangeRule("int", "float")],
    )
    assert (check.value, check.passed) == (0, True)
    assert check.describe() == (
        "no schema changes since the baseline (allowed: 'qty' int -> float; 'price' int -> float)"
    )
    # Rules that match nothing leave the usual message.
    clean = schema_change_check(changes(), [TypeChangeRule("int", "float")])
    assert (clean.passed, clean.tolerated) == (True, ())
    assert clean.describe() == "no columns added, removed or retyped since the baseline"


def test_a_column_rule_does_not_reach_other_columns() -> None:
    check = schema_change_check(
        changes(("qty", "int", "float"), ("price", "int", "float")),
        [TypeChangeRule("int", "float", "qty")],
    )
    assert (check.value, check.tolerated) == (1, (TypeChange("qty", "int", "float"),))
    assert check.detail == "'price' int -> float"


def test_added_and_removed_columns_always_count() -> None:
    comparison = Comparison(
        "x.csv", 2, 2, ("new",), ("old",), (TypeChange("q", "int", "float"),), ()
    )
    check = schema_change_check(comparison, [TypeChangeRule("int", "float")])
    assert (check.value, check.passed) == (2, False)
    assert check.describe() == (
        "2 schema changes since the baseline: added 'new'; removed 'old' "
        "(allowed: 'q' int -> float)"
    )


def test_repeated_rules_count_once_and_other_items_are_refused() -> None:
    rule = TypeChangeRule("int", "float")
    check = schema_change_check(
        changes(("q", "int", "float")), [rule, rule, TypeChangeRule("int", "float")]
    )
    assert check.allowed_rules == (rule,)
    with pytest.raises(TypeError, match="TypeChangeRule items"):
        schema_change_check(changes(), ["int:float"])  # type: ignore[list-item]


def test_json_lists_rules_and_tolerated_changes_only_with_rules(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(AFTER))
    comparison = changes(("qty", "int", "float"), ("code", "int", "string"))
    plain = json.loads(render_json(report, "a.csv", [schema_change_check(comparison)]))["checks"]
    assert plain == [
        {"check": "schema_change", "column": None, "limit": 0, "value": 2, "passed": False}
    ]
    rules = [TypeChangeRule("int", "float", "qty"), TypeChangeRule("date", "datetime")]
    with_rules = json.loads(render_json(report, "a.csv", [schema_change_check(comparison, rules)]))[
        "checks"
    ]
    assert with_rules == [
        {
            "check": "schema_change",
            "column": None,
            "limit": 0,
            "value": 1,
            "passed": False,
            "allowed_type_changes": [
                {"column": "qty", "before": "int", "after": "float"},
                {"column": None, "before": "date", "after": "datetime"},
            ],
            "tolerated": [{"column": "qty", "before": "int", "after": "float"}],
        }
    ]
    markdown = render_markdown(report, "a.csv", [schema_change_check(comparison, rules)])
    assert (
        "- FAIL: 1 schema change since the baseline: 'code' int -> string "
        "(allowed: 'qty' int -> float)\n"
    ) in markdown


# --- the command line ----------------------------------------------------


def test_cli_allows_the_named_widenings(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, data, err = run(
        write_csv,
        tmp_path,
        capsys,
        "--fail-on-schema-change",
        "--allow-type-change",
        "qty=int:float",
        "--allow-type-change",
        "date:datetime",
    )
    assert code == 8
    assert err == (
        "check failed: 1 schema change since the baseline: 'code' int -> string "
        "(allowed: 'qty' int -> float; 'day' date -> datetime)\n"
    )
    check = data["checks"][0]
    assert (check["value"], check["passed"]) == (1, False)
    assert [t["column"] for t in check["tolerated"]] == ["qty", "day"]
    # The comparison itself still lists every type change: it is informational.
    assert [t["column"] for t in data["baseline"]["type_changes"]] == ["qty", "day", "code"]


def test_cli_passes_when_every_change_is_allowed(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "id,qty,day,code\n1,3.5,2026-10-12 08:00,10\n2,4,2026-10-13 09:30,11\n"
    code, data, err = run(
        write_csv,
        tmp_path,
        capsys,
        "--fail-on-schema-change",
        "--allow-type-change",
        "int:float",
        "--allow-type-change",
        "date:datetime",
        text=text,
    )
    assert (code, err) == (0, "")
    assert data["checks"][0]["passed"] is True


def test_cli_without_the_option_is_byte_identical(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    after = str(write_csv(AFTER, "after.csv"))
    outputs = []
    for fmt in ("json", "markdown"):
        capsys.readouterr()
        assert (
            main([after, "--format", fmt, "--baseline", baseline, "--fail-on-schema-change"]) == 8
        )
        captured = capsys.readouterr()
        outputs.append((captured.out, captured.err))
    assert outputs[1][1] == (
        "check failed: 3 schema changes since the baseline: "
        "'qty' int -> float; 'day' date -> datetime; 'code' int -> string\n"
    )
    assert '"allowed_type_changes"' not in outputs[0][0] and '"tolerated"' not in outputs[0][0]


def test_cli_rules_follow_the_exact_direction(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, data, _ = run(
        write_csv,
        tmp_path,
        capsys,
        "--fail-on-schema-change",
        "--allow-type-change",
        "float:int",
        "--allow-type-change",
        "datetime:date",
        "--allow-type-change",
        "missing_column=int:string",
    )
    check = data["checks"][0]
    # None of the rules matches: a reverse pair, and a column the file lacks.
    assert (code, check["value"], check["tolerated"]) == (8, 3, [])
    assert check["allowed_type_changes"][2] == {
        "column": "missing_column",
        "before": "int",
        "after": "string",
    }


def test_cli_splits_the_name_at_the_last_equals_sign(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path, "id,a=b:c\n1,2\n")
    after = str(write_csv("id,a=b:c\n1,2.5\n", "after.csv"))
    capsys.readouterr()
    args = [after, "--baseline", baseline, "--fail-on-schema-change"]
    assert main([*args, "--allow-type-change", "a=b:c=int:float"]) == 0
    assert main([*args, "--allow-type-change", "a=int:float"]) == 8


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("int", "invalid --allow-type-change value: 'int' (use FROM:TO or NAME=FROM:TO)"),
        ("=int:float", "invalid --allow-type-change value: '=int:float' (use FROM:TO"),
        ("qty=int:float:string", "(use FROM:TO or NAME=FROM:TO)"),
        ("qty=integer:float", "(unknown column type 'integer'; use one of int, float"),
        ("qty=", "(use FROM:TO or NAME=FROM:TO)"),
        ("string:string", "(string:string is not a type change)"),
    ],
)
def test_cli_rejects_invalid_rules(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    value: str,
    message: str,
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    capsys.readouterr()
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                baseline,
                "--baseline",
                baseline,
                "--fail-on-schema-change",
                "--allow-type-change",
                value,
            ]
        )
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("with_baseline", "message"),
    [
        (False, "--allow-type-change needs --baseline"),
        (True, "--allow-type-change needs --fail-on-schema-change"),
    ],
)
def test_cli_needs_the_schema_gate(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    with_baseline: bool,
    message: str,
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    args = [str(write_csv(AFTER, "after.csv")), "--allow-type-change", "int:float"]
    if with_baseline:
        args += ["--baseline", baseline, "--max-row-drop", "10"]
    capsys.readouterr()
    with pytest.raises(SystemExit) as excinfo:
        main(args)
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err


def test_cli_column_rule_must_be_selected(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    after = str(write_csv(AFTER, "after.csv"))
    base = [after, "--baseline", baseline, "--fail-on-schema-change", "--columns", "id,qty"]
    capsys.readouterr()
    with pytest.raises(SystemExit) as excinfo:
        main([*base, "--allow-type-change", "code=int:string"])
    assert excinfo.value.code == 2
    assert (
        "--allow-type-change checks column 'code', which --columns leaves out"
        in capsys.readouterr().err
    )
    # A rule for any column, and one on a selected column, are fine.
    assert main([*base, "--allow-type-change", "qty=int:float"]) == 0
    assert main([*base, "--allow-type-change", "int:float"]) == 0


# --- the corpus -----------------------------------------------------------


def corpus_run(capsys: pytest.CaptureFixture[str], *options: str) -> tuple[int, str]:
    capsys.readouterr()
    code = main(
        [
            str(CORPUS / "stock_counts_week2.csv"),
            "--delimiter",
            "auto",
            "--decimal-comma",
            "--baseline",
            str(CORPUS / "expected" / "stock_counts_week1.json"),
            "--fail-on-schema-change",
            *options,
        ]
    )
    return code, capsys.readouterr().err


def test_corpus_weekly_stock_counts(capsys: pytest.CaptureFixture[str]) -> None:
    assert corpus_run(capsys) == (
        8,
        "check failed: 3 schema changes since the baseline: 'Lote' int -> string; "
        "'Cantidad' int -> float; 'Fecha conteo' date -> datetime\n",
    )
    allow = ("--allow-type-change", "Cantidad=int:float", "--allow-type-change", "date:datetime")
    assert corpus_run(capsys, *allow) == (
        8,
        "check failed: 1 schema change since the baseline: 'Lote' int -> string "
        "(allowed: 'Cantidad' int -> float; 'Fecha conteo' date -> datetime)\n",
    )
    # Allowing int:float everywhere still leaves the lot code: int -> string is another pair.
    code, err = corpus_run(
        capsys, "--allow-type-change", "int:float", "--allow-type-change", "date:datetime"
    )
    assert (code, "'Lote' int -> string" in err) == (8, True)
