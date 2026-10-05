"""Tests for ``--bool-words`` (issue #63)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.inference import bool_word_map, normalize_bool
from csv_quality_report.profile import build_report, profile_file, profile_rows
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]
FLAGS = "id;activo;pagado\n1;Sí;VERDADERO\n2;No;FALSO\n3;SÍ;falso\n4;no;Verdadero\n5;sí;TRUE\n"
SPANISH = (("sí", "no"), ("verdadero", "falso"))


def report_json(path: Path, capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *args]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


def test_bool_word_map_and_normalize() -> None:
    mapping = bool_word_map((("Sí", " No "), ("s", "n")))
    assert mapping == {
        "true": "true",
        "false": "false",
        "sí": "true",
        "no": "false",
        "s": "true",
        "n": "false",
    }
    assert [normalize_bool(v, mapping) for v in ["SÍ", "NO", "N", "True", "si", "x"]] == [
        "true",
        "false",
        "false",
        "true",
        "si",  # accents are not removed: si and sí are different words
        "x",
    ]
    assert bool_word_map(()) == {"true": "true", "false": "false"}


def test_casefold_matches_beyond_lower() -> None:
    # casefold() also folds characters that lower() keeps: "Groß".lower() is
    # "groß", but "Groß".casefold() is "gross", which matches the word.
    mapping = bool_word_map((("gross", "klein"),))
    assert normalize_bool("Groß", mapping) == "true"
    assert normalize_bool("KLEIN", mapping) == "false"


@pytest.mark.parametrize(
    ("pairs", "message"),
    [
        ((("si", "SI"),), "'si' and 'SI' are the same word"),
        ((("si", " "),), "two non-empty words"),
        ((("si",),), "two non-empty words"),
        ((("si", "no", "x"),), "two non-empty words"),
        ((("si", "no"), ("no", "x")), "'no' cannot mean both true and false"),
        ((("false", "true"),), "'false' cannot mean both true and false"),
        ((("1", "0"),), "'1' is a number or a date"),
        ((("yes", "1,5"),), "'1,5' is a number or a date"),  # a float with a decimal comma
        ((("2026-01-01", "x"),), "'2026-01-01' is a number or a date"),
    ],
)
def test_invalid_pairs(pairs: tuple[tuple[str, ...], ...], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        bool_word_map(pairs)  # type: ignore[arg-type]


def test_words_make_bool_columns(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--delimiter", ";", "--bool-words", "sí,no", "--bool-words", "verdadero,falso"]
    rep = report_json(write_csv(FLAGS), capsys, *args)
    activo, pagado = rep["columns"][1], rep["columns"][2]
    assert (activo["type"], pagado["type"]) == ("bool", "bool")
    # Top values and lengths keep the text as written.
    assert activo["top_values"][0] == {"value": "Sí", "count": 1}
    assert (pagado["min_length"], pagado["max_length"]) == (4, 9)
    assert rep["bool_words"] == [["sí", "no"], ["verdadero", "falso"]]


def test_without_the_option_nothing_changes(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = report_json(write_csv(FLAGS), capsys, "--delimiter", ";")
    assert [c["type"] for c in rep["columns"]] == ["int", "string", "string"]
    assert rep["bool_words"] == []


def test_stray_word_is_named_as_written(write_csv: WriteCsv) -> None:
    rows = "".join(f"{i};{'Sí' if i % 2 else 'No'}\n" for i in range(9)) + "9;Tal vez\n"
    report = profile_file(write_csv("id;ok\n" + rows), delimiter=";", bool_words=SPANISH)
    col = report.columns[1]
    assert col.type == "string"
    assert col.type_hint is not None
    assert (col.type_hint.type, col.type_hint.examples) == ("bool", ("Tal vez",))


def test_require_type_bool_passes_with_the_option(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [str(write_csv(FLAGS)), "--delimiter", ";", "--require-type", "activo=bool"]
    assert main(args) == 8
    capsys.readouterr()
    assert main([*args, "--bool-words", "SÍ,NO"]) == 0


def test_na_tokens_win_over_words(write_csv: WriteCsv) -> None:
    path = write_csv("ok\nsí\nno\nn/a\nn/a\n")
    report = profile_file(path, na_tokens=("n/a",), bool_words=(("sí", "no"), ("s", "n/a")))
    col = report.columns[0]
    assert (col.type, col.missing, col.distinct) == ("bool", 2, 2)


def test_other_columns_are_not_touched(write_csv: WriteCsv) -> None:
    # Words only change whole values: text that contains them stays text.
    path = write_csv("comentario;n\nno llegó;1\nsí, completo;2\nno;3\n")
    report = profile_file(path, delimiter=";", bool_words=SPANISH)
    assert [c.type for c in report.columns] == ["string", "int"]


def test_repeated_pairs_count_once(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    rep = report_json(write_csv(FLAGS), capsys, "--delimiter", ";", *["--bool-words", "sí,no"] * 2)
    assert rep["bool_words"] == [["sí", "no"]]


def test_markdown_lists_the_words(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv(FLAGS)
    assert main([str(path), "--delimiter", ";", "--bool-words", "s|i,n"]) == 0
    assert "\n- Boolean words (true/false): `s\\|i`/`n`\n" in capsys.readouterr().out
    assert main([str(path), "--delimiter", ";"]) == 0
    assert "Boolean words" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("si", "invalid --bool-words value: 'si' (use TRUE,FALSE, e.g. sí,no)"),
        ("si,", "invalid --bool-words value: 'si,'"),
        ("si,no,x", "invalid --bool-words value: 'si,no,x'"),
        ("1,0", "error: '1' is a number or a date, not a boolean word"),
        ("si,SI", "error: 'si' and 'SI' are the same word (case is ignored)"),
    ],
)
def test_invalid_cli_values_are_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], value: str, message: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([str(write_csv(FLAGS)), "--bool-words", value])
    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err


def test_conflicting_pairs_are_a_usage_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main([str(write_csv(FLAGS)), "--bool-words", "si,no", "--bool-words", "no,si"])
    assert "'no' cannot mean both true and false" in capsys.readouterr().err


def test_api_rejects_invalid_words_before_reading() -> None:
    def rows() -> Any:
        raise AssertionError("rows must not be read")
        yield  # pragma: no cover - makes this a generator

    with pytest.raises(ValueError, match="same word"):
        profile_rows(["ok"], rows(), bool_words=(("x", "X"),))


def test_streaming_and_in_memory_reports_agree(write_csv: WriteCsv) -> None:
    path = write_csv(FLAGS)
    streamed = profile_file(path, delimiter=";", bool_words=SPANISH)
    assert streamed == build_report(read_table(path, delimiter=";"), bool_words=SPANISH)
    assert streamed.bool_words == SPANISH


def test_combined_with_other_rewrites(write_csv: WriteCsv) -> None:
    path = write_csv("ok;fecha;monto\nsí;05/10/2026;1.234,5\nno;06/10/2026;10\n")
    report = profile_file(
        path,
        delimiter=";",
        decimal_comma=True,
        thousands=".",
        date_order="dmy",
        bool_words=SPANISH,
    )
    assert [c.type for c in report.columns] == ["bool", "date", "float"]
