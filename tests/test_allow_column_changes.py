"""Tests for ``--allow-added-column`` and ``--allow-removed-column`` (issue #134).

Both tolerate named column changes on the ``--fail-on-schema-change`` gate,
like ``--allow-type-change`` does for type changes (ADR 0007).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report import Comparison
from csv_quality_report.checks import CHECK_SCHEMA_CHANGE, TypeChangeRule, schema_change_check
from csv_quality_report.cli import main
from csv_quality_report.compare import TypeChange
from csv_quality_report.profile import profile_file
from csv_quality_report.render import render_json, render_markdown

WriteCsv = Callable[..., Path]
ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
# The export gains a unit column and loses its lot column; quantities stay whole.
BEFORE = "id,qty,lot,day\n1,3,4102,2026-10-05\n2,4,4107,2026-10-06\n"
AFTER = "id,qty,unit,day\n1,3,un,2026-10-12\n2,4,kg,2026-10-13\n"


def columns(
    added: tuple[str, ...] = (), removed: tuple[str, ...] = (), *types: tuple[str, str, str]
) -> Comparison:
    """A comparison with these added and removed columns and (column, before, after) changes."""
    return Comparison("x.csv", 2, 2, added, removed, tuple(TypeChange(*t) for t in types), ())


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
    fmt: str = "json",
) -> tuple[int, str, str]:
    """Run the CLI on ``text`` against the BEFORE baseline; (exit code, stdout, stderr)."""
    baseline = write_baseline(write_csv, tmp_path)
    after = str(write_csv(text, "after.csv"))
    capsys.readouterr()
    code = main([after, "--format", fmt, "--baseline", baseline, *options])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def check_of(output: str) -> dict[str, Any]:
    item: dict[str, Any] = json.loads(output)["checks"][0]
    return item


# --- the check ------------------------------------------------------------


def test_without_names_the_check_is_unchanged() -> None:
    comparison = columns(("unit",), ("lot",), ("qty", "int", "float"))
    check = schema_change_check(comparison)
    assert check == schema_change_check(comparison, (), (), ())
    assert (check.allowed_added, check.tolerated_added) == ((), ())
    assert (check.allowed_removed, check.tolerated_removed) == ((), ())
    assert check.describe() == (
        "3 schema changes since the baseline: added 'unit'; removed 'lot'; 'qty' int -> float"
    )


def test_an_allowed_added_column_is_not_counted_and_is_listed() -> None:
    check = schema_change_check(columns(("unit", "note"), ("lot",)), allowed_added_columns=["unit"])
    assert (check.check, check.value, check.limit, check.passed) == (
        CHECK_SCHEMA_CHANGE,
        2,
        0,
        False,
    )
    assert (check.allowed_added, check.tolerated_added) == (("unit",), ("unit",))
    assert check.detail == "added 'note'; removed 'lot'"
    assert check.describe() == (
        "2 schema changes since the baseline: added 'note'; removed 'lot' (allowed: added 'unit')"
    )


def test_an_allowed_removed_column_is_not_counted_and_is_listed() -> None:
    check = schema_change_check(
        columns(("unit",), ("lot", "zone")), allowed_removed_columns=["lot"]
    )
    assert (check.value, check.passed) == (2, False)
    assert (check.allowed_removed, check.tolerated_removed) == (("lot",), ("lot",))
    assert check.describe() == (
        "2 schema changes since the baseline: added 'unit'; removed 'zone' (allowed: removed 'lot')"
    )


def test_a_check_with_only_allowed_changes_passes_and_lists_them_in_order() -> None:
    check = schema_change_check(
        columns(("unit",), ("lot",), ("qty", "int", "float")),
        [TypeChangeRule("int", "float")],
        ["unit"],
        ["lot"],
    )
    assert (check.value, check.passed, check.detail) == (0, True, "")
    # Added, then removed, then type changes: the order of the failure message.
    assert check.describe() == (
        "no schema changes since the baseline "
        "(allowed: added 'unit'; removed 'lot'; 'qty' int -> float)"
    )


def test_names_match_exactly_and_only_their_own_direction() -> None:
    comparison = columns(("Unit",), ("lot",))
    # Case-sensitive, no stripping, and an added name does not allow a removal.
    check = schema_change_check(comparison, (), ["unit", " Unit", "lot"], ["Unit"])
    assert (check.value, check.tolerated_added, check.tolerated_removed) == (2, (), ())
    assert check.describe() == "2 schema changes since the baseline: added 'Unit'; removed 'lot'"


def test_names_that_match_nothing_leave_the_usual_message() -> None:
    check = schema_change_check(columns(), (), ["unit"], ["lot"])
    assert (check.passed, check.allowed_added, check.allowed_removed) == (True, ("unit",), ("lot",))
    assert check.describe() == "no columns added, removed or retyped since the baseline"


def test_a_rename_is_allowed_by_naming_both_columns() -> None:
    check = schema_change_check(
        columns(("Lote proveedor",), ("Lote",)), (), ["Lote proveedor"], ["Lote"]
    )
    assert check.passed
    assert check.describe() == (
        "no schema changes since the baseline (allowed: added 'Lote proveedor'; removed 'Lote')"
    )


def test_repeated_names_count_once_and_other_items_are_refused() -> None:
    check = schema_change_check(columns(("unit",)), (), ["unit", "unit"], ("lot", "lot"))
    assert (check.allowed_added, check.allowed_removed) == (("unit",), ("lot",))
    with pytest.raises(TypeError, match="allowed_added_columns takes column names, not 3"):
        schema_change_check(columns(), (), [3])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="not one string 'unit'"):
        schema_change_check(columns(), (), "unit")
    with pytest.raises(ValueError, match="allowed_removed_columns takes non-empty column names"):
        schema_change_check(columns(), (), (), [""])


def test_json_carries_each_pair_of_fields_only_with_its_option(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(AFTER))
    comparison = columns(("unit", "note"), ("lot",))

    def item(*names: list[str]) -> dict[str, Any]:
        check = schema_change_check(comparison, (), *names)
        data: dict[str, Any] = json.loads(render_json(report, "a.csv", [check]))["checks"][0]
        return data

    plain = {"check": "schema_change", "column": None, "limit": 0, "value": 3, "passed": False}
    assert item() == plain
    assert item(["unit"]) == {
        **plain,
        "value": 2,
        "allowed_added_columns": ["unit"],
        "tolerated_added_columns": ["unit"],
    }
    assert item([], ["lot", "zone"]) == {
        **plain,
        "value": 2,
        "allowed_removed_columns": ["lot", "zone"],
        "tolerated_removed_columns": ["lot"],
    }
    both = item(["unit", "extra"], ["lot"])
    assert list(both) == [
        *plain,
        "allowed_added_columns",
        "tolerated_added_columns",
        "allowed_removed_columns",
        "tolerated_removed_columns",
    ]
    assert (both["value"], both["tolerated_added_columns"]) == (1, ["unit"])
    markdown = render_markdown(report, "a.csv", [schema_change_check(comparison, (), ["unit"])])
    assert (
        "- FAIL: 2 schema changes since the baseline: added 'note'; removed 'lot' "
        "(allowed: added 'unit')\n"
    ) in markdown


def test_json_with_type_rules_keeps_its_fields_first(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(AFTER))
    comparison = columns(("unit",), (), ("qty", "int", "float"))
    check = schema_change_check(comparison, [TypeChangeRule("int", "float")], ["unit"])
    item = json.loads(render_json(report, "a.csv", [check]))["checks"][0]
    assert list(item)[5:] == [
        "allowed_type_changes",
        "tolerated",
        "allowed_added_columns",
        "tolerated_added_columns",
    ]
    assert item["tolerated"] == [{"column": "qty", "before": "int", "after": "float"}]


# --- the command line ----------------------------------------------------


def test_cli_allows_the_added_column(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run(
        write_csv, tmp_path, capsys, "--fail-on-schema-change", "--allow-added-column", "unit"
    )
    assert code == 8
    assert err == (
        "check failed: 1 schema change since the baseline: removed 'lot' (allowed: added 'unit')\n"
    )
    check = check_of(out)
    assert (check["value"], check["passed"]) == (1, False)
    assert (check["allowed_added_columns"], check["tolerated_added_columns"]) == (
        ["unit"],
        ["unit"],
    )
    assert "allowed_removed_columns" not in check and "tolerated" not in check
    # The comparison still lists every added and removed column.
    baseline = json.loads(out)["baseline"]
    assert (baseline["added_columns"], baseline["removed_columns"]) == (["unit"], ["lot"])


def test_cli_passes_when_both_columns_are_allowed(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    options = (
        "--fail-on-schema-change",
        "--allow-added-column",
        "unit",
        "--allow-removed-column",
        "lot",
    )
    code, out, err = run(write_csv, tmp_path, capsys, *options)
    assert (code, err) == (0, "")
    check = check_of(out)
    assert (check["passed"], check["tolerated_removed_columns"]) == (True, ["lot"])
    code, markdown, err = run(write_csv, tmp_path, capsys, *options, fmt="markdown")
    assert (code, err) == (0, "")
    assert (
        "- pass: no schema changes since the baseline (allowed: added 'unit'; removed 'lot')\n"
    ) in markdown


def test_cli_combines_with_type_rules(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "id,qty,unit,day\n1,3.5,kg,2026-10-12\n2,4,un,2026-10-13\n"
    code, out, err = run(
        write_csv,
        tmp_path,
        capsys,
        "--fail-on-schema-change",
        "--allow-removed-column",
        "lot",
        "--allow-type-change",
        "qty=int:float",
        text=text,
    )
    assert code == 8
    assert err == (
        "check failed: 1 schema change since the baseline: added 'unit' "
        "(allowed: removed 'lot'; 'qty' int -> float)\n"
    )
    assert check_of(out)["tolerated"] == [{"column": "qty", "before": "int", "after": "float"}]


def test_cli_without_the_options_is_byte_identical(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for fmt in ("json", "markdown"):
        code, out, err = run(write_csv, tmp_path, capsys, "--fail-on-schema-change", fmt=fmt)
        assert code == 8
        assert (
            err
            == "check failed: 2 schema changes since the baseline: added 'unit'; removed 'lot'\n"
        )
        assert "allowed" not in out and "tolerated" not in out


def test_cli_names_that_match_nothing_still_fail_the_real_changes(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(
        write_csv,
        tmp_path,
        capsys,
        "--fail-on-schema-change",
        "--allow-added-column",
        "Unit",
        "--allow-removed-column",
        "unit",
    )
    check = check_of(out)
    assert (code, check["value"]) == (8, 2)
    assert (check["tolerated_added_columns"], check["tolerated_removed_columns"]) == ([], [])


def test_cli_takes_the_name_exactly_as_written(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path, "id,a\n1,2\n")
    after = str(write_csv('id,a,"x,y=z"\n1,2,3\n', "after.csv"))
    args = [after, "--baseline", baseline, "--fail-on-schema-change"]
    capsys.readouterr()
    assert main([*args, "--allow-added-column", "x,y=z"]) == 0
    assert main([*args, "--allow-added-column", "x"]) == 8


@pytest.mark.parametrize("option", ["--allow-added-column", "--allow-removed-column"])
@pytest.mark.parametrize("value", ["", "  "])
def test_cli_rejects_an_empty_name(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    option: str,
    value: str,
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    capsys.readouterr()
    with pytest.raises(SystemExit) as excinfo:
        main([baseline, "--baseline", baseline, "--fail-on-schema-change", option, value])
    assert excinfo.value.code == 2
    assert f"invalid {option} value: {value!r} (no name)" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("option", "what"),
    [("--allow-added-column", "added columns"), ("--allow-removed-column", "removed columns")],
)
@pytest.mark.parametrize("with_baseline", [False, True])
def test_cli_needs_the_schema_gate(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    option: str,
    what: str,
    with_baseline: bool,
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    args = [str(write_csv(AFTER, "after.csv")), option, "unit"]
    if with_baseline:
        args += ["--baseline", baseline, "--max-row-drop", "10"]
        message = (
            f"{option} needs --fail-on-schema-change ({what} only fail the run with that gate)"
        )
    else:
        message = f"{option} needs --baseline"
    capsys.readouterr()
    with pytest.raises(SystemExit) as excinfo:
        main(args)
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err


def test_cli_type_rule_message_is_unchanged(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    capsys.readouterr()
    with pytest.raises(SystemExit):
        main([baseline, "--baseline", baseline, "--allow-type-change", "int:float"])
    assert (
        "--allow-type-change needs --fail-on-schema-change "
        "(type changes only fail the run with that gate)"
    ) in capsys.readouterr().err


@pytest.mark.parametrize(
    ("option", "name"), [("--allow-added-column", "unit"), ("--allow-removed-column", "lot")]
)
def test_cli_name_must_be_selected(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    option: str,
    name: str,
) -> None:
    baseline = write_baseline(write_csv, tmp_path)
    after = str(write_csv(AFTER, "after.csv"))
    base = [after, "--baseline", baseline, "--fail-on-schema-change", "--columns", "id,qty"]
    capsys.readouterr()
    with pytest.raises(SystemExit) as excinfo:
        main([*base, option, name])
    assert excinfo.value.code == 2
    assert f"{option} checks column '{name}', which --columns leaves out" in (
        capsys.readouterr().err
    )
    # On the selected columns nothing was added or removed.
    assert main([*base, option, "qty"]) == 0


# --- the corpus -----------------------------------------------------------


def test_corpus_week3_counts_tolerate_the_named_columns() -> None:
    names = ["stock_counts_week3_schema", "stock_counts_week3_allowed_added"]
    checks = [
        json.loads((CORPUS / "expected" / f"{name}.json").read_text(encoding="utf-8"))["checks"][0]
        for name in [*names, "stock_counts_week3_allowed"]
    ]
    assert [c["value"] for c in checks] == [2, 1, 0]
    assert [c["passed"] for c in checks] == [False, False, True]
    assert checks[2]["tolerated_added_columns"] == ["Unidad"]
    assert checks[2]["tolerated_removed_columns"] == ["Lote"]
