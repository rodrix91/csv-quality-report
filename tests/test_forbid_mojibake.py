"""Tests for ``--forbid-mojibake NAME`` (issue #306)."""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import build_report, evaluate, read_table
from csv_quality_report.checks import CHECK_MOJIBAKE, CHECK_REQUIRED_COLUMN
from csv_quality_report.cli import main
from csv_quality_report.profile import MojibakeProfile, profile_file, unmojibake

WriteCsv = Callable[..., Path]


def garble(text: str) -> str:
    """``text`` as UTF-8 read as Windows-1252 (ISO-8859-1 for its five unassigned bytes)."""
    return "".join(
        bytes([byte]).decode("cp1252", errors="ignore") or chr(byte)
        for byte in text.encode("utf-8")
    )


# A customer list where some rows went through a tool that read the UTF-8
# file as Windows-1252 ("PeÃ±a", once padded, which counts as its stripped
# value), one where a decoder replaced a letter ("Mu�oz"), "s/d" and an
# empty cell are missing.
DATA = (
    "Cliente;Provincia;Monto\n"
    "Peña;Córdoba;10\n"
    "PeÃ±a;CÃ³rdoba;12\n"
    " PeÃ±a ;Neuquén;5\n"
    "Mu�oz;Entre RÃ­os;3\n"
    "s/d;SÃO PAULO;1\n"
    ";Tucumán;2\n"
)


def mojibake(path: Path, name: str = "Cliente", **options: object) -> MojibakeProfile:
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        forbid_mojibake=(name,),
        **options,  # type: ignore[arg-type]
    )
    (found,) = report.mojibake
    return found


# --- what counts as garbled ------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "repaired"),
    [
        ("PeÃ±a", "Peña"),
        ("CÃ³rdoba", "Córdoba"),
        ("GÃ©nero", "Género"),
        ("Entre RÃ­os", "Entre Ríos"),  # í is C3 AD: AD shows as a soft hyphen
        ("ÃRBOL", None),  # "Á" is C3 81: 0x81 is unassigned in Windows-1252 ...
        ("Ã\u0081RBOL", "ÁRBOL"),  # ... so readers show it as the C1 control U+0081
        ("Ã\u008dNDICE", "ÍNDICE"),  # 0x8D, also unassigned
        ("NÂ°", "N°"),
        ("Â¿QuÃ©?", "¿Qué?"),
        ("itâ€™s", "it’s"),  # three bytes, two of them Windows-1252 extras
        ("â‚¬ 10", "€ 10"),
        ("SÃ£o Paulo", "São Paulo"),
        ("PeÃƒÂ±a", "Peña"),  # garbled twice
        (garble(garble(garble("Ñandú"))), "Ñandú"),  # three times
        ("Mu�oz", "Mu�oz"),  # letters lost: nothing to repair
        ("�", "�"),
        ("Ã�", "Ã�"),
    ],
)
def test_garbled_values(value: str, repaired: str | None) -> None:
    assert unmojibake(value) == repaired


@pytest.mark.parametrize(
    "value",
    [
        "Peña",
        "Córdoba",
        "MUÑOZ",
        "SÃO PAULO",  # Portuguese: C3 4F is not UTF-8
        "São Paulo",
        "Ã",
        "N°",
        "Nº 12",
        "1ª cuota",
        "¿Qué?",
        "«PERÚ»",
        "ACCIÓN—RÁPIDA",
        "Peña PeÃ±a",  # a correct accent next to a garbled one
        "€ 10",
        "Ñandú",
        "Ελλάδα",
        "東京",
        "",
        "Pena",
    ],
)
def test_other_values(value: str) -> None:
    assert unmojibake(value) is None


@pytest.mark.parametrize("value", [None, 7, b"Pe\xc3\x83\xc2\xb1a"])
def test_values_that_are_not_text(value: object) -> None:
    assert unmojibake(value) is None  # type: ignore[arg-type]


def test_every_spanish_and_portuguese_letter_round_trips() -> None:
    letters = "áéíóúüñÁÉÍÓÚÜÑçÇãõÃÕâêôÂÊÔàÀ°ºª¿¡€"
    for letter in letters:
        word = f"x{letter}y"
        assert unmojibake(word) is None, word
        assert unmojibake(garble(word)) == word, word


def test_correct_text_with_two_accents_in_a_row_is_not_garbled() -> None:
    # Any two or three accented Spanish or Portuguese letters in a row, in any
    # case, stay as they are.
    letters = "áéíóúüñÁÉÍÓÚÜÑçÇãõÃÕ"
    for run in itertools.chain(
        itertools.product(letters, repeat=2), itertools.product(letters, repeat=3)
    ):
        word = "a" + "".join(run) + "b"
        assert unmojibake(word) is None, word


def test_the_documented_exception() -> None:
    # The only correct text that forms UTF-8: a capital accented letter
    # directly followed by a symbol, with no other accent (see ``unmojibake``).
    assert unmojibake("PERÚ»") is not None
    assert unmojibake("É¿") is not None
    assert unmojibake("«PERÚ»") is None


# --- measuring in the profile ------------------------------------------------


def test_cells_and_examples(write_csv: WriteCsv) -> None:
    found = mojibake(write_csv(DATA))
    assert found == MojibakeProfile(
        column="Cliente",
        cells=3,
        examples=(("PeÃ±a", 2), ("Mu�oz", 1)),
    )


def test_another_column(write_csv: WriteCsv) -> None:
    found = mojibake(write_csv(DATA), "Provincia")
    assert found == MojibakeProfile(
        column="Provincia",
        cells=2,
        examples=(("CÃ³rdoba", 1), ("Entre RÃ­os", 1)),
    )


def test_top_limits_the_examples_not_the_count(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    one = mojibake(path, top_n=1)
    assert (one.cells, one.examples) == (3, (("PeÃ±a", 2),))
    none = mojibake(path, top_n=0)
    assert (none.cells, none.examples) == (3, ())


def test_the_profile_agrees_with_unmojibake(write_csv: WriteCsv) -> None:
    # The profile tests only the values that are not ASCII; it must count
    # exactly the values ``unmojibake`` takes as garbled, in the order first seen.
    parts = ["", "a", "Ã", "±", "Â", "°", "ñ", "�", "€", "â", "\u0081"]
    values = list(dict.fromkeys("".join(p) for p in itertools.product(parts, repeat=4)))
    values = [v for v in values if v.strip() == v and v and v != "s/d"]
    path = write_csv("x;y\n" + "".join(f"{v};1\n" for v in values))
    found = mojibake(path, "x", top_n=len(values))
    expected = tuple((v, 1) for v in values if unmojibake(v) is not None)
    assert len(expected) >= 500
    assert (found.cells, found.examples) == (len(expected), expected)


def test_the_profile_finds_every_garbled_character(write_csv: WriteCsv) -> None:
    # Every character a Windows-1252 export can hold, garbled, is found by the
    # profile, whose prefilter looks for a lead and a continuation character.
    chars = [chr(code) for code in range(0x80, 0x100)]
    chars += [c for b in range(0x80, 0xA0) for c in bytes([b]).decode("cp1252", "ignore")]
    values = [garble(f"x{char}y") for char in chars]
    path = write_csv("x;y\n" + "".join(f"{v};1\n" for v in values))
    found = mojibake(path, "x", top_n=0)
    assert found.cells == len(values) == 128 + 27


def test_the_profile_finds_text_garbled_by_an_iso_8859_1_reader(write_csv: WriteCsv) -> None:
    # An ISO-8859-1 reader shows bytes 80-9F as C1 controls (U+0080-U+009F),
    # where Windows-1252 shows "€", "’" and the like.
    chars = [chr(code) for code in range(0x80, 0x100)] + ["€", "’", "…"]
    values = [f"x{char}y".encode().decode("latin-1") for char in chars]
    path = write_csv("x;y\n" + "".join(f"{v};1\n" for v in values))
    assert mojibake(path, "x", top_n=0).cells == len(values) == 131
    assert unmojibake("it\u00e2\u0080\u0099s") == "it’s"


def test_ties_keep_the_first_seen_value(write_csv: WriteCsv) -> None:
    path = write_csv("x;y\nCÃ³rdoba;1\nPeÃ±a;1\n")
    assert mojibake(path, "x").examples == (("CÃ³rdoba", 1), ("PeÃ±a", 1))


def test_a_clean_column(write_csv: WriteCsv) -> None:
    found = mojibake(write_csv(DATA), "Monto")
    assert found == MojibakeProfile(column="Monto", cells=0)


def test_missing_cells_are_not_checked(write_csv: WriteCsv) -> None:
    # "Â°" is listed as a missing-value text, so it is not checked.
    path = write_csv("x;y\nÂ°;1\nNÂ°;1\n;1\n")
    report = profile_file(path, delimiter=";", na_tokens=("Â°",), forbid_mojibake=("x",))
    assert report.mojibake == (MojibakeProfile(column="x", cells=1, examples=(("NÂ°", 1),)),)


def test_a_cp1252_file_read_with_its_encoding_is_clean(write_csv: WriteCsv) -> None:
    # The right --encoding gives correct text, which is never garbled.
    path = write_csv("x;y\nPeña;Córdoba\nNº 3;¿Qué?\n".encode("cp1252"))
    report = profile_file(path, delimiter=";", encoding="cp1252", forbid_mojibake=("x", "y"))
    assert [m.cells for m in report.mojibake] == [0, 0]


def test_a_value_seen_only_in_a_later_batch_is_found(write_csv: WriteCsv) -> None:
    rows = "".join(f"Peña {i};1\n" for i in range(25_000))
    path = write_csv("Cliente;x\n" + rows + "PeÃ±a;1\n")
    assert mojibake(path).examples == (("PeÃ±a", 1),)
    assert mojibake(path, max_rows=25_000).cells == 0


def test_unprofiled_and_unknown_columns_are_skipped(write_csv: WriteCsv) -> None:
    report = profile_file(
        write_csv(DATA),
        delimiter=";",
        columns=("Monto",),
        forbid_mojibake=("Cliente", "Nada"),
    )
    assert report.mojibake == ()


def test_build_report_measures_the_same(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    table = read_table(path, delimiter=";")
    built = build_report(table, na_tokens=("s/d",), forbid_mojibake=["Cliente"])
    assert built.mojibake == (mojibake(path),)


def test_no_names_no_profiles(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv(DATA), delimiter=";").mojibake == ()


# --- evaluate() ----------------------------------------------------------------

PREFIX = "with text garbled by a wrong encoding (UTF-8 read as Windows-1252, or characters "
PREFIX += "replaced by U+FFFD; fix the step that converted the file)"


def checked(path: Path, **options: object) -> list[tuple[str, str | None, bool, str]]:
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("s/d",),
        forbid_mojibake=("Cliente", "Monto", "Provincia"),
        **options,  # type: ignore[arg-type]
    )
    checks = evaluate(report, forbid_mojibake=["Cliente", "Monto", "Cliente", "Provincia"])
    return [(c.check, c.column, c.passed, c.describe()) for c in checks]


def test_evaluate_fails_passes_and_describes(write_csv: WriteCsv) -> None:
    assert checked(write_csv(DATA)) == [
        (
            CHECK_MOJIBAKE,
            "Cliente",
            False,
            f"column 'Cliente' has 3 cells {PREFIX}: "
            '"PeÃ±a" in 2 cells (probably "Peña"), "Mu�oz" in 1 cell (characters lost)',
        ),
        (
            CHECK_MOJIBAKE,
            "Monto",
            True,
            "column 'Monto' has no text garbled by a wrong encoding",
        ),
        (
            CHECK_MOJIBAKE,
            "Provincia",
            False,
            # The soft hyphen of "í" garbled is escaped so that it can be seen.
            f"column 'Provincia' has 2 cells {PREFIX}: "
            '"CÃ³rdoba" in 1 cell (probably "Córdoba"), '
            '"Entre RÃ\\u00ados" in 1 cell (probably "Entre Ríos")',
        ),
    ]


def test_evaluate_escapes_invisible_characters_in_the_repair(write_csv: WriteCsv) -> None:
    # A garbled zero-width space (E2 80 8B) repairs to an invisible character.
    path = write_csv("Cliente;Monto;Provincia\nPeâ€‹a;1;x\n")
    (cliente, _, _) = checked(path)
    assert cliente[3] == (
        f"column 'Cliente' has 1 cell {PREFIX}: "
        '"Peâ€‹a" in 1 cell (probably "Pe\\u200ba")'.replace("â€‹", "â€‹")
    )


def test_evaluate_singular_and_without_examples(write_csv: WriteCsv) -> None:
    path = write_csv("Cliente;Monto;Provincia\nGÃ©nero;1;x\nGénero;2;y\n")
    (cliente, _, _) = checked(path)
    assert cliente[3] == (
        f'column \'Cliente\' has 1 cell {PREFIX}: "GÃ©nero" in 1 cell (probably "Género")'
    )
    (cliente, _, _) = checked(path, top_n=0)
    assert cliente[3] == f"column 'Cliente' has 1 cell {PREFIX}"


def test_evaluate_needs_the_names_in_the_report(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA), delimiter=";")
    with pytest.raises(ValueError, match="'Cliente' has a mojibake check but the report"):
        evaluate(report, forbid_mojibake=["Cliente"])


def test_unknown_and_unprofiled_columns(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    report = profile_file(path, delimiter=";")
    checks = evaluate(report, forbid_mojibake=["Clientes"])
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "Clientes", False)
    ]
    narrow = profile_file(path, delimiter=";", columns=("Monto",))
    with pytest.raises(ValueError, match="column 'Cliente' has a per-column check"):
        evaluate(narrow, forbid_mojibake=["Cliente"])


# --- command line --------------------------------------------------------------


def run(write_csv: WriteCsv, *args: str, data: str = DATA) -> int:
    return main([str(write_csv(data)), "--delimiter", "auto", "--na", "s/d", *args])


def test_cli_fails(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(write_csv, "--top", "1", "--forbid-mojibake", "Cliente")
    out, err = capsys.readouterr()
    assert code == 8
    assert err == (
        f"check failed: column 'Cliente' has 3 cells {PREFIX}: "
        '"PeÃ±a" in 2 cells (probably "Peña")\n'
    )
    assert "- FAIL: column 'Cliente' has 3 cells with text garbled" in out


def test_cli_passes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--forbid-mojibake", "Monto") == 0
    out = capsys.readouterr().out
    assert "- pass: column 'Monto' has no text garbled by a wrong encoding" in out


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--format", "json", "--forbid-mojibake", "Cliente") == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check == {
        "check": "mojibake",
        "column": "Cliente",
        "limit": 0,
        "value": 3,
        "passed": False,
        "mojibake": {"PeÃ±a": 2, "Mu�oz": 1},
    }


def test_cli_json_of_a_passing_check(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json", "--forbid-mojibake", "Monto") == 0
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check["mojibake"] == {}
    assert check["passed"] is True


def test_cli_repeated_name_gives_one_check(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ("--format", "json", "--forbid-mojibake", "Cliente", "--forbid-mojibake", "Cliente")
    assert run(write_csv, *args) == 8
    assert len(json.loads(capsys.readouterr().out)["checks"]) == 1


def test_cli_name_with_commas_and_equals_signs(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("a=b,c;d\nPeÃ±a;1\n")
    assert main([str(path), "--delimiter", ";", "--forbid-mojibake", "a=b,c"]) == 8
    assert "column 'a=b,c' has 1 cell with text garbled" in capsys.readouterr().err


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json") == 0
    assert "mojibake" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--forbid-mojibake", ""], "invalid --forbid-mojibake value: '' (no name)"),
        (["--forbid-mojibake", "  "], "invalid --forbid-mojibake value: '  ' (no name)"),
        (
            ["--columns", "Monto", "--forbid-mojibake", "Cliente"],
            "--forbid-mojibake checks column 'Cliente', which --columns leaves out",
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
    assert run(write_csv, "--forbid-mojibake", "Clientes") == 8
    assert "required column 'Clientes' is missing" in capsys.readouterr().err
