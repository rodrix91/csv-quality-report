"""Tests for ``--columns`` (issue #89)."""

from __future__ import annotations

import gzip
import io
import json
import random
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.checks import evaluate
from csv_quality_report.cli import main
from csv_quality_report.errors import EXIT_USAGE, ColumnSelectionError
from csv_quality_report.profile import build_report, profile_file, profile_rows
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]
DATA = (
    "id,peso,ciudad,fecha\n"
    "1,12.5,La Paz,2026-01-05\n2,-1,Tarija,2026-02-10\n1,12.5,La Paz,2026-01-05\n"
)


def report_json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert main([*args, "--format", "json"]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


def test_only_selected_columns_in_the_given_order(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = report_json(capsys, str(write_csv(DATA)), "--columns", "fecha,peso")
    assert [c["name"] for c in rep["columns"]] == ["fecha", "peso"]
    assert (rep["selected_columns"], rep["header_columns"]) == (["fecha", "peso"], 4)
    # Rows are read whole: the duplicate row is still found.
    assert (rep["rows"], rep["duplicate_rows"]) == (3, 1)


def test_default_reports_every_column(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = report_json(capsys, str(write_csv(DATA)))
    assert (rep["selected_columns"], rep["header_columns"], len(rep["columns"])) == (None, 4, 4)


@pytest.mark.parametrize(
    "selection", [["peso"], ["fecha", "id"], ["ciudad", "peso", "fecha", "id"]]
)
def test_selected_profiles_equal_the_full_profiles(
    write_csv: WriteCsv, selection: list[str]
) -> None:
    path = write_csv(DATA)
    full = {c.name: c for c in profile_file(path).columns}
    part = profile_file(path, columns=selection)
    assert [c.name for c in part.columns] == selection
    assert all(c == full[c.name] for c in part.columns)


def test_equivalence_on_random_wide_rows() -> None:
    rng = random.Random(89)
    header = [f"c{i}" for i in range(12)]
    rows = [
        [rng.choice(["", "x", "1", "2.5", " 3 ", "2026-01-01", "true", "NA"]) for _ in header]
        for _ in range(3000)
    ]
    full = profile_rows(header, rows, na_tokens=("NA",))
    for _ in range(20):
        chosen = rng.sample(header, rng.randint(1, len(header)))
        part = profile_rows(header, rows, na_tokens=("NA",), columns=chosen)
        assert [c.name for c in part.columns] == chosen
        by_name = {c.name: c for c in full.columns}
        assert all(c == by_name[c.name] for c in part.columns)
        assert (part.rows, part.duplicate_rows) == (full.rows, full.duplicate_rows)


def test_repeated_names_count_once(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    rep = report_json(capsys, str(write_csv(DATA)), "--columns", "peso, peso ,id")
    assert rep["selected_columns"] == ["peso", "id"]
    report = profile_file(write_csv(DATA), columns=["id", "id"])
    assert report.selected_columns == ("id",)
    assert [c.name for c in report.columns] == ["id"]  # profiled once


def test_markdown_says_how_many_were_selected(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(DATA))
    assert main([path, "--columns", "peso"]) == 0
    assert "\n- Columns: 1 of 4 (selected)\n" in capsys.readouterr().out
    assert main([path]) == 0
    assert "\n- Columns: 4\n" in capsys.readouterr().out


def test_unknown_column_is_a_usage_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(DATA)
    assert main([str(path), "--columns", "peso,Total,Fecha"]) == EXIT_USAGE == 2
    assert capsys.readouterr().err == (
        "error: selected columns 'Total', 'Fecha' are not in the header "
        "(columns: id, peso, ciudad, fecha)\n"
    )
    with pytest.raises(ColumnSelectionError, match=r"^selected column 'x' is not in the header"):
        profile_file(path, columns=["x"])


def test_padded_header_name_is_suggested(write_csv: WriteCsv) -> None:
    with pytest.raises(ColumnSelectionError, match=r"did you mean ' b'\?$"):
        profile_file(write_csv("a, b,c\n1,2,3\n"), columns=["b"])


def test_long_headers_are_cut_in_the_message() -> None:
    header = [f"c{i}" for i in range(15)]
    with pytest.raises(ColumnSelectionError, match=r"\(columns: c0, c1, .*, c9, \.\.\.\)$"):
        profile_rows(header, [], columns=["x"])


def test_empty_selection_is_rejected() -> None:
    with pytest.raises(ColumnSelectionError, match="no columns selected"):
        profile_rows(["a"], [["1"]], columns=[])


def test_selection_is_checked_before_reading_rows() -> None:
    def rows() -> Any:
        raise AssertionError("rows must not be read")
        yield  # pragma: no cover - makes this a generator

    with pytest.raises(ColumnSelectionError):
        profile_rows(["a", "b"], rows(), columns=["c"])


def test_required_columns_use_the_full_header(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(DATA))
    assert main([path, "--columns", "peso", "--require-columns", "id,ciudad"]) == 0
    assert main([path, "--columns", "peso", "--require-columns", "Total"]) == 8
    assert "required column 'Total' is missing (columns: id, peso, ciudad, fecha)" in (
        capsys.readouterr().err
    )


@pytest.mark.parametrize(
    "gate",
    [
        ["--max-missing-column", "id=0"],
        ["--require-type", "id=int"],
        ["--range", "id=0:"],
        ["--number-affix", "$", "--max-affixes", "id=1"],
    ],
)
def test_gates_on_unselected_columns_are_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], gate: list[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(DATA)), "--columns", "peso", *gate])
    assert excinfo.value.code == 2
    assert "checks column 'id', which --columns leaves out" in capsys.readouterr().err


def test_gates_on_selected_columns_work(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(DATA))
    assert main([path, "--columns", "peso", "--range", "peso=0:"]) == 8
    assert "column 'peso' has values outside 0.. (min -1, max 12.5)" in capsys.readouterr().err
    # --max-missing applies to the selected columns only.
    blank = str(write_csv("a,b\n1,\n2,\n", "blank.csv"))
    assert main([blank, "--columns", "a", "--max-missing", "0"]) == 0


def test_evaluate_refuses_a_check_on_an_unprofiled_column(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA), columns=["peso"])
    with pytest.raises(ValueError, match="column 'id' has a per-column check but was not selected"):
        evaluate(report, column_types={"id": "int"})
    (check,) = evaluate(report, column_types={"nope": "int"})
    assert (check.check, check.passed) == ("required_column", False)


def test_streaming_in_memory_stdin_and_gzip_agree(
    write_csv: WriteCsv, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_csv(DATA)
    streamed = profile_file(path, columns=["fecha", "peso"])
    assert streamed == build_report(read_table(path), columns=["fecha", "peso"])
    buffer = io.BufferedReader(io.BytesIO(gzip.compress(DATA.encode())))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(buffer, encoding="utf-8"))
    from_stdin = profile_file(Path("-"), columns=["fecha", "peso"])
    assert from_stdin.columns == streamed.columns
    assert (from_stdin.header, from_stdin.compressed) == (streamed.header, True)


def test_duplicate_header_names_are_selected_by_their_suffix(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("a,a,b\n1,2,3\n"), columns=["a_2"])
    assert [(c.name, c.min) for c in report.columns] == [("a_2", 2)]
    assert report.header == ("a", "a_2", "b")
