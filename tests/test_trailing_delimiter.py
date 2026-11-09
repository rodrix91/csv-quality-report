"""Tests for ``--trailing-delimiter``: lines that end with the field separator (issue #299)."""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.errors import DelimiterDetectionError, RaggedRowError
from csv_quality_report.profile import TrailingDelimiters, build_report, profile_file
from csv_quality_report.reader import (
    detect_delimiter,
    open_rows,
    read_table,
    trailing_header,
    trailing_row,
)
from csv_quality_report.render import render_json, render_markdown

WriteCsv = Callable[..., Path]
HINT = "if the lines end with a delimiter, read them with --trailing-delimiter"
# The three shapes of a point-of-sale export: rows only, header only, both.
ROWS_ONLY = "Codigo;Producto;Cantidad\r\nA1;Yerba;3;\r\nA2;Mate;5;\r\n"
HEADER_ONLY = "Codigo;Producto;Cantidad;\r\nA1;Yerba;3\r\nA2;Mate;5\r\n"
BOTH = "Codigo;Producto;Cantidad;\r\nA1;Yerba;3;\r\nA2;Mate;5;\r\n"


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


def run_json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    code, out, err = run(capsys, *args, "--format", "json")
    assert (code, err) == (0, "")
    report: dict[str, Any] = json.loads(out)
    return report


@pytest.mark.parametrize(
    ("text", "header", "rows"),
    [(ROWS_ONLY, False, 2), (HEADER_ONLY, True, 0), (BOTH, True, 2)],
)
def test_each_shape_is_read_with_the_header_columns(
    write_csv: WriteCsv,
    capsys: pytest.CaptureFixture[str],
    text: str,
    header: bool,
    rows: int,
) -> None:
    path = str(write_csv(text))
    for delimiter in (";", "auto"):
        report = run_json(capsys, path, "--delimiter", delimiter, "--trailing-delimiter")
        assert report["trailing_delimiter"] == {"header": header, "rows": rows}
        assert report["header_columns"] == 3
        assert [c["name"] for c in report["columns"]] == ["Codigo", "Producto", "Cantidad"]
        assert [c["missing"] for c in report["columns"]] == [0, 0, 0]
        assert report["columns"][2]["type"] == "int"
        assert report["delimiter"] == ";"


def test_the_json_key_sits_after_the_skip_counts(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv("Titulo\r\n" + ROWS_ONLY + "Total\r\n"))
    args = ("--delimiter", ";", "--skip-lines", "1", "--skip-footer", "1")
    report = run_json(capsys, path, *args, "--trailing-delimiter")
    keys = list(report)
    assert keys.index("trailing_delimiter") == keys.index("skipped_footer") + 1
    assert keys.index("na_tokens") == keys.index("trailing_delimiter") + 1
    # The footer record is dropped first and never looked at.
    assert (report["rows"], report["trailing_delimiter"]["rows"]) == (2, 2)


@pytest.mark.parametrize("text", [ROWS_ONLY, HEADER_ONLY])
def test_without_the_option_a_ragged_row_suggests_it(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    code, out, err = run(capsys, str(write_csv(text)), "--delimiter", ";")
    assert (code, out) == (6, "")
    assert err.endswith(f"(from the header); {HINT}\n")
    assert "--skip-footer" not in err  # the misleading footer hint of a two-row file


@pytest.mark.parametrize("text", [ROWS_ONLY, HEADER_ONLY])
def test_without_the_option_detection_suggests_it(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    code, out, err = run(capsys, str(write_csv(text)), "--delimiter", "auto")
    assert (code, out) == (7, "")
    assert err.endswith(f"pass it explicitly with --delimiter; {HINT}\n")


def test_without_the_option_both_give_a_phantom_column(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # Why the option exists when header and rows both end with the delimiter.
    report = run_json(capsys, str(write_csv(BOTH)), "--delimiter", ";")
    assert "trailing_delimiter" not in report
    phantom = report["columns"][-1]
    assert (report["header_columns"], phantom["name"], phantom["missing_pct"]) == (4, "", 100.0)


@pytest.mark.parametrize(
    "line",
    [
        "A2;Mate;5;x",  # an extra value is data, not a trailing delimiter
        "A2;Mate;5;;",  # two extra fields
        "A2;Mate;5; ",  # a blank extra field is not an empty one
        "A2;Mate",  # a short row
    ],
)
def test_other_ragged_rows_still_fail(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], line: str
) -> None:
    path = str(write_csv(f"Codigo;Producto;Cantidad\nA1;Yerba;3;\n{line}\nA3;Te;1;\n"))
    code, out, err = run(capsys, path, "--delimiter", ";", "--trailing-delimiter")
    assert (code, out) == (6, "")
    assert err.startswith("error: row at line 3 has ")
    assert HINT not in err  # the option is already given


@pytest.mark.parametrize(
    "text",
    [
        "a;b;c\n1;2;3;x\n",  # an extra value
        "a;b;c\n1;2;3;;\n",  # two extra fields
        "a;b;c\n1;2\n",  # a short row under a header without a trailing delimiter
        "a;b;c;\n1;2\n",  # two fields short of a header that ends with one
    ],
)
def test_no_hint_when_the_option_would_not_help(write_csv: WriteCsv, text: str) -> None:
    with pytest.raises(RaggedRowError) as info, open_rows(write_csv(text), delimiter=";") as rows:
        list(rows)
    assert HINT not in info.value.message


def test_no_hint_for_a_short_row_once_the_header_was_trimmed(write_csv: WriteCsv) -> None:
    # The header lost its empty last field; a row one field shorter than that
    # is damaged, and the option, already given, is not suggested again.
    path = write_csv("a;b;c;\n1;2;3\n1;2\n4;5;6\n")
    with (
        pytest.raises(RaggedRowError) as info,
        open_rows(path, delimiter=";", trailing_delimiter=True) as rows,
    ):
        list(rows)
    assert info.value.message == "row at line 3 has 2 fields, expected 3 (from the header)"


def test_no_detection_hint_when_the_option_would_not_help(write_csv: WriteCsv) -> None:
    with pytest.raises(DelimiterDetectionError) as info:
        read_table(write_csv("a;b;c\n1;2;3;x\n1;2\n"), delimiter="auto")
    assert HINT not in info.value.message


def test_no_detection_hint_for_a_one_column_result(write_csv: WriteCsv) -> None:
    # Read with the rule, "a;" and "b" are one column each: that is not a fix.
    with pytest.raises(DelimiterDetectionError) as info:
        read_table(write_csv("a;\nb\n"), delimiter="auto")
    assert HINT not in info.value.message
    table = read_table(write_csv("a;\nb\n"), delimiter="auto", trailing_delimiter=True)
    assert (table.delimiter, table.header, table.rows) == (",", ["a;"], [["b"]])


def test_no_detection_hint_once_the_option_is_given(write_csv: WriteCsv) -> None:
    with pytest.raises(DelimiterDetectionError) as info:
        read_table(write_csv("a;b;c\n1;2;3;x\n"), delimiter="auto", trailing_delimiter=True)
    assert HINT not in info.value.message


def test_a_title_line_is_suggested_rather_than_the_option(write_csv: WriteCsv) -> None:
    # Dropping the title fixes detection; the option alone would not.
    with pytest.raises(DelimiterDetectionError) as info:
        read_table(write_csv("Ventas del dia\n" + BOTH), delimiter="auto")
    assert "--skip-lines 1" in info.value.message
    assert HINT not in info.value.message


def test_a_one_column_header_gets_the_trailing_hint(write_csv: WriteCsv) -> None:
    # "Codigo" alone is not a title above a header: its rows end with a delimiter.
    path = write_csv("Codigo\nA1;\nA2;\n")
    with pytest.raises(RaggedRowError) as info, open_rows(path, delimiter=";") as rows:
        list(rows)
    assert info.value.message.endswith(HINT)
    assert "--skip-lines" not in info.value.message
    table = read_table(path, delimiter=";", trailing_delimiter=True)
    assert (table.header, table.rows, table.trailing_rows) == (["Codigo"], [["A1"], ["A2"]], 2)


def test_rows_of_the_header_width_are_kept_as_they_are(write_csv: WriteCsv) -> None:
    # Only some lines end with the delimiter; a row whose last cell is empty
    # without one keeps it as a missing value.
    text = "a;b;c\n1;2;3;\n4;5;6\n7;8;\n9;10;;\n"
    table = read_table(write_csv(text), delimiter=";", trailing_delimiter=True)
    assert table.rows == [["1", "2", "3"], ["4", "5", "6"], ["7", "8", ""], ["9", "10", ""]]
    assert (table.trailing_header, table.trailing_rows) == (False, 2)


def test_a_quoted_empty_last_field_is_an_empty_field(write_csv: WriteCsv) -> None:
    # The csv module cannot tell "" from nothing; both are an empty extra field.
    table = read_table(write_csv('a;b\n1;2;""\n"3;4";5;\n'), delimiter=";", trailing_delimiter=True)
    assert table.rows == [["1", "2"], ["3;4", "5"]]


def test_a_quoted_delimiter_in_the_last_column_is_kept(write_csv: WriteCsv) -> None:
    table = read_table(write_csv('a;b\n1;"x;"\n2;"y;";\n'), delimiter=";", trailing_delimiter=True)
    assert (table.rows, table.trailing_rows) == ([["1", "x;"], ["2", "y;"]], 1)


def test_an_empty_header_name_that_is_not_last_is_kept(write_csv: WriteCsv) -> None:
    table = read_table(write_csv("a;;c;\n1;2;3;\n"), delimiter=";", trailing_delimiter=True)
    assert (table.header, table.rows, table.trailing_header) == (
        ["a", "", "c"],
        [["1", "2", "3"]],
        True,
    )


def test_a_header_with_only_an_empty_field_is_kept(write_csv: WriteCsv) -> None:
    # A one-field header is never shortened to no columns.
    table = read_table(write_csv('""\nx\n'), delimiter=";", trailing_delimiter=True)
    assert (table.header, table.rows, table.trailing_header) == ([""], [["x"]], False)


def test_only_one_trailing_header_field_is_dropped(write_csv: WriteCsv) -> None:
    table = read_table(write_csv("a;b;;\n1;2;;\n"), delimiter=";", trailing_delimiter=True)
    assert (table.header, table.rows) == (["a", "b", ""], [["1", "2", ""]])
    assert (table.trailing_header, table.trailing_rows) == (True, 1)


def test_max_rows_counts_the_rows_read(write_csv: WriteCsv) -> None:
    text = "a;b\n" + "".join(f"{i};x;\n" for i in range(5))
    with open_rows(write_csv(text), delimiter=";", max_rows=2, trailing_delimiter=True) as rows:
        assert list(rows) == [["0", "x"], ["1", "x"]]
        assert (rows.truncated, rows.trailing_rows) == (True, 2)


def test_the_defaults_are_unchanged(write_csv: WriteCsv) -> None:
    path = write_csv(BOTH)
    with open_rows(path, delimiter=";") as rows:
        assert rows.header == ["Codigo", "Producto", "Cantidad", ""]
        assert list(rows) == [["A1", "Yerba", "3", ""], ["A2", "Mate", "5", ""]]
        assert (rows.trailing_delimiter, rows.trailing_header, rows.trailing_rows) == (
            False,
            False,
            0,
        )
    table = read_table(path, delimiter=";")
    assert (table.trailing_delimiter, table.trailing_header, table.trailing_rows) == (
        False,
        False,
        0,
    )
    assert profile_file(path, delimiter=";").trailing_delimiter is None


def test_the_python_api(write_csv: WriteCsv) -> None:
    path = write_csv(BOTH)
    table = read_table(path, delimiter="auto", trailing_delimiter=True)
    assert (table.header, table.trailing_delimiter) == (["Codigo", "Producto", "Cantidad"], True)
    assert (table.trailing_header, table.trailing_rows) == (True, 2)
    report = profile_file(path, delimiter="auto", trailing_delimiter=True)
    assert report.trailing_delimiter == TrailingDelimiters(header=True, rows=2)
    assert build_report(table) == report


@pytest.mark.parametrize("api", ["stream", "table", "profile"])
@pytest.mark.parametrize("invalid", [1, 0, "yes", None, 1.0])
def test_a_value_that_is_not_a_bool_is_rejected_before_opening(
    tmp_path: Path, api: str, invalid: Any
) -> None:
    missing = tmp_path / "does-not-exist.csv"
    with pytest.raises(ValueError, match="trailing_delimiter must be a bool"):
        if api == "stream":
            with open_rows(missing, trailing_delimiter=invalid):
                pass  # pragma: no cover - never reached
        elif api == "table":
            read_table(missing, trailing_delimiter=invalid)
        else:
            profile_file(missing, trailing_delimiter=invalid)


@pytest.mark.parametrize(
    ("dropped", "line"),
    [
        (TrailingDelimiters(header=True, rows=2), "dropped from the header and 2 rows"),
        (TrailingDelimiters(header=False, rows=1), "dropped from 1 row"),
        (TrailingDelimiters(header=True, rows=0), "dropped from the header"),
        (TrailingDelimiters(header=False, rows=0), "none found"),
    ],
)
def test_the_markdown_line(write_csv: WriteCsv, dropped: TrailingDelimiters, line: str) -> None:
    report = replace(profile_file(write_csv("a,b\n1,2\n")), trailing_delimiter=dropped)
    lines = render_markdown(report, "x.csv").splitlines()
    assert lines.index(f"- Trailing delimiter: {line}") == lines.index("- Columns: 2") + 1
    data = json.loads(render_json(report, "x.csv"))
    assert data["trailing_delimiter"] == {"header": dropped.header, "rows": dropped.rows}


def test_reports_without_the_option_have_no_line(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("a,b\n1,2\n"))
    assert "Trailing delimiter" not in render_markdown(report, "x.csv")
    assert "trailing_delimiter" not in json.loads(render_json(report, "x.csv"))


def test_trailing_header_and_trailing_row() -> None:
    assert trailing_header(["a", "b", ""]) == ["a", "b"]
    assert trailing_header(["a", ""]) == ["a"]
    assert trailing_header([""]) == [""]
    assert trailing_header(["a", "b"]) == ["a", "b"]
    assert trailing_header(["a", " "]) == ["a", " "]
    assert trailing_row(["1", "2", ""], 2)
    assert not trailing_row(["1", "2", "x"], 2)
    assert not trailing_row(["1", "2", " "], 2)
    assert not trailing_row(["1", "2"], 2)
    assert not trailing_row(["1", "2", "", ""], 2)


@pytest.mark.parametrize("text", [ROWS_ONLY, HEADER_ONLY, BOTH])
def test_detect_delimiter_with_the_rule(text: str) -> None:
    assert detect_delimiter(text, trailing_delimiter=True) == ";"


def test_detect_delimiter_without_the_rule() -> None:
    with pytest.raises(DelimiterDetectionError):
        detect_delimiter(ROWS_ONLY)
    assert detect_delimiter(BOTH) == ";"  # four fields everywhere


def test_detection_is_unchanged_on_files_without_a_trailing_delimiter() -> None:
    for text in ("a;b\n1;2\n", "a,b\n1,2\n", "a\tb\n1\t2\n", "a\n1\n", "a;b\n1;2;3\n"):
        try:
            expected: str | type[DelimiterDetectionError] = detect_delimiter(text)
        except DelimiterDetectionError:
            expected = DelimiterDetectionError
        try:
            got: str | type[DelimiterDetectionError] = detect_delimiter(
                text, trailing_delimiter=True
            )
        except DelimiterDetectionError:
            got = DelimiterDetectionError
        assert got == expected, text


@pytest.mark.parametrize("seed", range(20))
def test_equivalent_to_the_file_without_trailing_delimiters(write_csv: WriteCsv, seed: int) -> None:
    """Appending the delimiter to random lines changes nothing but the counts."""
    rng = random.Random(seed)
    width = rng.randint(2, 5)
    cells = ["", "1", "2,5", "x", '"a;b"', "05/10/2026", "s/d", "VERDADERO"]
    header = [f"c{i}" for i in range(width)]
    rows = [[rng.choice(cells) for _ in range(width)] for _ in range(rng.randint(1, 30))]
    lines = [";".join(header)] + [";".join(row) for row in rows]
    marked = [rng.random() < 0.7 for _ in lines]
    plain = write_csv("\n".join(lines) + "\n", name="plain.csv")
    ended = write_csv(
        "\n".join(line + (";" if mark else "") for line, mark in zip(lines, marked, strict=True))
        + "\n",
        name="ended.csv",
    )
    options: dict[str, Any] = {
        "decimal_comma": True,
        "date_order": "dmy",
        "na_tokens": ("s/d",),
        "bool_words": (("verdadero", "falso"),),
    }
    for delimiter in (";", "auto"):
        try:
            expected = profile_file(plain, delimiter=delimiter, **options)
        except DelimiterDetectionError:  # a comma in "2,5" can make "," fit too
            with pytest.raises(DelimiterDetectionError):
                profile_file(ended, delimiter=delimiter, trailing_delimiter=True, **options)
            continue
        got = profile_file(ended, delimiter=delimiter, trailing_delimiter=True, **options)
        assert got.trailing_delimiter == TrailingDelimiters(marked[0], sum(marked[1:]))
        assert replace(got, trailing_delimiter=None) == expected
