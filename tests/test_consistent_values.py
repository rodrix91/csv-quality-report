"""Tests for ``--consistent-values NAME`` (issue #288)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import build_report, evaluate, read_table
from csv_quality_report.checks import CHECK_CONSISTENT_VALUES, CHECK_REQUIRED_COLUMN
from csv_quality_report.cli import main
from csv_quality_report.profile import VariantProfile, profile_file, variant_key

WriteCsv = Callable[..., Path]
# Branches of a consolidated sales export typed by hand: "Cochabamba" in three
# cases (one padded, which counts as the plain spelling), "Santa Cruz" once with
# two spaces, "Ñuñoa" once without its tildes, "s/d" and an empty cell missing.
DATA = (
    "Sucursal;Monto\n"
    "Cochabamba;1\n"
    "COCHABAMBA;2\n"
    " Cochabamba ;3\n"
    "cochabamba;4\n"
    "Santa Cruz;5\n"
    "Santa  Cruz;6\n"
    "Santa Cruz;7\n"
    "La Paz;8\n"
    "Ñuñoa;1\n"
    "Nunoa;1\n"
    "s/d;3\n"
    ";3\n"
)
COCHABAMBA = (("Cochabamba", 2), ("COCHABAMBA", 1), ("cochabamba", 1))
SANTA_CRUZ = (("Santa Cruz", 2), ("Santa  Cruz", 1))
NUNOA = (("Ñuñoa", 1), ("Nunoa", 1))


def variants(path: Path, name: str = "Sucursal", **options: object) -> VariantProfile:
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        consistent_values=(name,),
        **options,  # type: ignore[arg-type]
    )
    (found,) = report.variants
    return found


# --- the comparison key --------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("COCHABAMBA", "cochabamba"),
        ("Santa  Cruz", "santa cruz"),  # two spaces
        ("Santa Cruz", "santa cruz"),  # a non-breaking space pasted from Excel
        ("Santa \t Cruz", "santa cruz"),
        ("Ñuñoa", "nunoa"),  # composed ñ
        ("Ñuñoa", "nunoa"),  # decomposed ñ
        ("Paraná", "parana"),
        ("Straße", "strasse"),  # case folding, not just lower()
        ("ＬＡ ＰＡＺ", "la paz"),  # full-width letters (compatibility forms)
        ("ℌola", "hola"),  # a letter that decomposes into an upper-case one
        ("m²", "m2"),
        ("Li\u200bma", "lima"),  # a zero-width space
        ("Tuc\u00adumán", "tucuman"),  # a soft hyphen
        ("0001", "0001"),  # digits and punctuation are kept
        ("S.A.", "s.a."),
    ],
)
def test_variant_key(value: str, key: str) -> None:
    assert variant_key(value) == key


def test_the_fast_paths_agree_with_the_definition() -> None:
    # Every ASCII value takes the shortcut; its key must be the one the full
    # Unicode folding would give.
    from unicodedata import category, combining, normalize

    def slow(value: str) -> str:
        folded = normalize("NFKD", normalize("NFKD", value).casefold())
        kept = (c for c in folded if not combining(c) and category(c) != "Cf")
        return " ".join("".join(kept).split())

    for code in range(128):
        value = f"A{chr(code)}b  C"
        assert variant_key(value) == slow(value)
    # The translation table that drops combining marks and format characters
    # classifies each code point on first use; it must agree with the
    # character-by-character definition, on first use and once cached.
    for _ in range(2):
        for code in range(0x80, 0x30000, 3):
            if 0xD800 <= code <= 0xDFFF:
                continue  # surrogates cannot be decoded from a file
            value = f"É{chr(code)}x"
            assert variant_key(value) == slow(value), hex(code)


# --- measuring in the profile ------------------------------------------------


def test_groups_cells_and_spellings(write_csv: WriteCsv) -> None:
    found = variants(write_csv(DATA))
    assert found == VariantProfile(
        column="Sucursal",
        groups=3,
        cells=4,  # COCHABAMBA, cochabamba, "Santa  Cruz" and Nunoa
        examples=(COCHABAMBA, SANTA_CRUZ, NUNOA),  # the default --top is 3
    )


def test_groups_with_more_cells_to_fix_come_first(write_csv: WriteCsv) -> None:
    cities = ["lima", "Tacna", "TACNA", "tacna", "Lima", "Lima", "LIMA", "LIMA", "LIMA", "Piura"]
    path = write_csv("Ciudad;x\n" + "".join(f"{city};1\n" for city in cities))
    found = variants(path, "Ciudad")
    # Lima: LIMA 3, Lima 2, lima 1 (3 cells to fix); Tacna 1 each (2 to fix).
    assert found.groups == 2
    assert found.cells == 5
    assert found.examples == (
        (("LIMA", 3), ("Lima", 2), ("lima", 1)),
        (("Tacna", 1), ("TACNA", 1), ("tacna", 1)),  # first seen first on ties
    )


def test_groups_are_ranked_by_cells_to_fix_not_by_size(write_csv: WriteCsv) -> None:
    # Oruro has 11 cells but 1 to fix; Sucre has 4 cells and 2 to fix.
    cities = ["Oruro"] * 10 + ["ORURO"] + ["Sucre", "Sucre", "SUCRE", "SUCRE"]
    path = write_csv("Ciudad;x\n" + "".join(f"{city};1\n" for city in cities))
    found = variants(path, "Ciudad", top_n=1)
    assert (found.cells, found.examples) == (3, ((("Sucre", 2), ("SUCRE", 2)),))


def test_ties_between_groups_keep_the_order_of_their_first_spelling(
    write_csv: WriteCsv,
) -> None:
    # "b" is seen before "a" but its second spelling comes after A's.
    found = variants(write_csv("x;y\nb;1\na;1\nA;1\nB;1\n"), "x")
    assert found.examples == ((("b", 1), ("B", 1)), (("a", 1), ("A", 1)))


def test_top_limits_the_groups_listed_not_the_counts(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    one = variants(path, top_n=1)
    assert (one.groups, one.cells, one.examples) == (3, 4, (COCHABAMBA,))
    none = variants(path, top_n=0)
    assert (none.groups, none.cells, none.examples) == (3, 4, ())


def test_a_consistent_column(write_csv: WriteCsv) -> None:
    assert variants(write_csv(DATA), "Monto") == VariantProfile(column="Monto", groups=0, cells=0)


def test_missing_cells_are_not_values(write_csv: WriteCsv) -> None:
    # Without --na, "s/d" and "S/D" are two spellings of one value.
    path = write_csv("x;y\ns/d;1\nS/D;1\nok;1\n")
    report = profile_file(path, delimiter=";", consistent_values=("x",))
    assert report.variants[0].groups == 1
    # With --na s/d --na-ignore-case both are missing, so nothing is left to compare.
    found = variants(path, "x", na_ignore_case=True)
    assert (found.groups, found.cells) == (0, 0)


def test_a_spelling_seen_only_in_a_later_batch_is_found(write_csv: WriteCsv) -> None:
    rows = "".join(f"La Paz;{i}\n" for i in range(25_000))
    path = write_csv("Sucursal;Monto\n" + rows + "LA PAZ;1\n")
    assert variants(path).examples == ((("La Paz", 25_000), ("LA PAZ", 1)),)
    assert variants(path, max_rows=25_000).groups == 0


def test_numbers_compare_as_text(write_csv: WriteCsv) -> None:
    # 7 and 7.0 are the same number but not spellings of one another.
    path = write_csv("x;y\n7;1\n7.0;1\n7;1\n")
    assert variants(path, "x").groups == 0


def test_unprofiled_and_unknown_columns_are_skipped(write_csv: WriteCsv) -> None:
    report = profile_file(
        write_csv(DATA),
        delimiter=";",
        columns=("Monto",),
        consistent_values=("Sucursal", "Nada"),
    )
    assert report.variants == ()


def test_build_report_measures_the_same(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    table = read_table(path, delimiter=";")
    built = build_report(table, na_tokens=("s/d",), consistent_values=["Sucursal"])
    assert built.variants == (variants(path),)


def test_no_names_no_variants(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv(DATA), delimiter=";").variants == ()


# --- evaluate() ----------------------------------------------------------------


def checked(path: Path, **options: object) -> list[tuple[str, str | None, bool, str]]:
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        consistent_values=("Sucursal", "Monto"),
        **options,  # type: ignore[arg-type]
    )
    checks = evaluate(report, consistent_values=["Sucursal", "Monto", "Sucursal"])
    return [(c.check, c.column, c.passed, c.describe()) for c in checks]


def test_evaluate_fails_passes_and_describes(write_csv: WriteCsv) -> None:
    assert checked(write_csv(DATA)) == [
        (
            CHECK_CONSISTENT_VALUES,
            "Sucursal",
            False,
            "column 'Sucursal' has 3 values written in more than one way (4 cells differ "
            'from the most common spelling): "Cochabamba" in 2 cells, "COCHABAMBA" in 1, '
            '"cochabamba" in 1; "Santa Cruz" in 2 cells, "Santa  Cruz" in 1; '
            '"Ñuñoa" in 1 cell, "Nunoa" in 1',
        ),
        (CHECK_CONSISTENT_VALUES, "Monto", True, "column 'Monto' has every value written one way"),
    ]


def test_evaluate_singular_and_without_examples(write_csv: WriteCsv) -> None:
    path = write_csv("Sucursal;Monto\nSucre;1\nSUCRE;2\nSucre;3\n")
    (sucursal, _) = checked(path)
    assert sucursal[3] == (
        "column 'Sucursal' has 1 value written in more than one way (1 cell differs from "
        'the most common spelling): "Sucre" in 2 cells, "SUCRE" in 1'
    )
    (sucursal, _) = checked(path, top_n=0)
    assert sucursal[3] == (
        "column 'Sucursal' has 1 value written in more than one way (1 cell differs from "
        "the most common spelling)"
    )


def test_long_groups_are_shortened_in_the_message(write_csv: WriteCsv) -> None:
    # Twelve spellings of one value: "a b" and eleven wider runs of inner whitespace.
    spellings = ["a b"] * 2 + ["a" + " " * n + "b" for n in range(2, 13)]
    path = write_csv("Sucursal;Monto\n" + "".join(f"{s};1\n" for s in spellings))
    (sucursal, _) = checked(path)
    message = sucursal[3]
    assert message.endswith(", ... (12 spellings)")
    assert message.count('" in ') == 10
    report = profile_file(path, delimiter=";", consistent_values=("Sucursal",))
    (check,) = evaluate(report, consistent_values=["Sucursal"])
    assert len(check.variants[0]) == 12  # the check keeps every spelling


def test_exactly_ten_spellings_are_all_listed(write_csv: WriteCsv) -> None:
    spellings = ["a b"] * 2 + ["a" + " " * n + "b" for n in range(2, 11)]
    path = write_csv("Sucursal;Monto\n" + "".join(f"{s};1\n" for s in spellings))
    (sucursal, _) = checked(path)
    assert "..." not in sucursal[3]
    assert sucursal[3].count('" in ') == 10


def test_invisible_differences_are_shown_escaped(write_csv: WriteCsv) -> None:
    values = [
        "Buenos Aires",
        "Buenos Aires",
        "Buenos\u00a0Aires",
        "Buenos\u200b Aires",
        "Buenos\U000e0020 Aires",
    ]
    path = write_csv("Sucursal;Monto\n" + "".join(f"{v};1\n" for v in values))
    (sucursal, _) = checked(path)
    assert sucursal[3].endswith(
        '"Buenos Aires" in 2 cells, "Buenos\\u00a0Aires" in 1, "Buenos\\u200b Aires" in 1, '
        '"Buenos\\U000e0020 Aires" in 1'
    )
    report = profile_file(path, delimiter=";", consistent_values=("Sucursal",))
    (check,) = evaluate(report, consistent_values=["Sucursal"])
    assert check.variants[0][1] == ("Buenos\u00a0Aires", 1)  # the value itself is kept


def test_evaluate_needs_the_names_in_the_report(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA), delimiter=";")
    with pytest.raises(ValueError, match="'Sucursal' has a consistent_values check but the"):
        evaluate(report, consistent_values=["Sucursal"])


def test_unknown_and_unprofiled_columns(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    report = profile_file(path, delimiter=";")
    checks = evaluate(report, consistent_values=["Sucursl"])
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "Sucursl", False)
    ]
    narrow = profile_file(path, delimiter=";", columns=("Monto",))
    with pytest.raises(ValueError, match="column 'Sucursal' has a per-column check"):
        evaluate(narrow, consistent_values=["Sucursal"])


# --- command line --------------------------------------------------------------


def run(write_csv: WriteCsv, *args: str, data: str = DATA) -> int:
    return main([str(write_csv(data)), "--delimiter", "auto", "--na", "s/d", *args])


def test_cli_fails(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(write_csv, "--top", "1", "--consistent-values", "Sucursal")
    out, err = capsys.readouterr()
    assert code == 8
    assert err == (
        "check failed: column 'Sucursal' has 3 values written in more than one way "
        '(4 cells differ from the most common spelling): "Cochabamba" in 2 cells, '
        '"COCHABAMBA" in 1, "cochabamba" in 1\n'
    )
    assert "- FAIL: column 'Sucursal' has 3 values" in out


def test_cli_passes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--consistent-values", "Monto") == 0
    assert "- pass: column 'Monto' has every value written one way" in capsys.readouterr().out


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--format", "json", "--top", "2", "--consistent-values", "Sucursal") == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check == {
        "check": "consistent_values",
        "column": "Sucursal",
        "limit": 0,
        "value": 4,
        "passed": False,
        "variant_groups": 3,
        "variants": [
            [
                {"value": "Cochabamba", "cells": 2},
                {"value": "COCHABAMBA", "cells": 1},
                {"value": "cochabamba", "cells": 1},
            ],
            [{"value": "Santa Cruz", "cells": 2}, {"value": "Santa  Cruz", "cells": 1}],
        ],
    }


def test_cli_name_with_commas_and_equals_signs(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a=b,c;d\nx;1\nX;1\n")
    assert main([str(path), "--delimiter", ";", "--consistent-values", "a=b,c"]) == 8
    assert "column 'a=b,c' has 1 value written" in capsys.readouterr().err


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json") == 0
    out = capsys.readouterr().out
    assert "variant" not in out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--consistent-values", ""], "invalid --consistent-values value: '' (no name)"),
        (["--consistent-values", "  "], "invalid --consistent-values value: '  ' (no name)"),
        (
            ["--columns", "Monto", "--consistent-values", "Sucursal"],
            "--consistent-values checks column 'Sucursal', which --columns leaves out",
        ),
    ],
)
def test_cli_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(write_csv, *args)
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_cli_unknown_column(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--consistent-values", "Sucursl") == 8
    assert "required column 'Sucursl' is missing" in capsys.readouterr().err
