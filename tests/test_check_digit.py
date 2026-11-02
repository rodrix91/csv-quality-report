"""Tests for ``--check-digit NAME=SCHEME`` (issue #247)."""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from csv_quality_report import build_report, evaluate, read_table, render_markdown
from csv_quality_report.checkdigits import (
    SCHEMES,
    check_scheme,
    scheme_label,
    valid_cnpj,
    valid_cpf,
    valid_cuit,
    valid_gtin,
    valid_rut,
    validator,
)
from csv_quality_report.checks import CHECK_CHECK_DIGIT, CHECK_REQUIRED_COLUMN
from csv_quality_report.cli import main
from csv_quality_report.profile import CheckDigitProfile, profile_file, profile_rows

WriteCsv = Callable[..., Path]

# A supplier master: AFIP's own CUIT (33-69345023-9) is a published valid
# number; the others were built with their check digit, then mistyped.
DATA = (
    "Proveedor;CUIT;EAN\n"
    "AFIP;33-69345023-9;4006381333931\n"
    "Molino;30-71234567-1; 7791234567898 \n"
    "Aceitera;30-71234576-1;7791234567889\n"
    "Bodega;s/d;036000291452\n"
    "Imprenta;;7,79123E+12\n"
    "Granja;30-71234576-1;96385074\n"
    "Lácteos;30712345671;\n"
)

# Published or independently built valid identifiers, as written in exports.
VALID = {
    "cuit": ["33-69345023-9", "30-71234567-1", "30712345671", "20-33445566-2"],
    "rut": ["60.803.000-K", "60803000k", "11.111.111-1", "12.345.678-5", "76.086.428-5", "1-9"],
    "cpf": ["529.982.247-25", "52998224725", "123.456.789-09"],
    "cnpj": ["11.222.333/0001-81", "11222333000181", "12.ABC.345/01DE-35"],
    "gtin": ["4006381333931", "036000291452", "96385074", "10012345678902", "7791234567898"],
}
INVALID = {
    # wrong check digit, wrong length, letters, a remainder that needs 10
    "cuit": ["33-69345023-8", "3369345023", "336934502390", "AB-69345023-9", "20-00000001-0"],
    "rut": [
        "60.803.000-1",
        "12.345.678-K",
        "123456789-2",  # a 9-digit body, with its digit
        "K",
        "",
        "-",
        "1.2A3-4",
        "12345678-X",
    ],
    # repeated digits pass the arithmetic but are not issued
    "cpf": ["529.982.247-24", "111.111.111-11", "000.000.000-00", "5299822472", "52998224725A"],
    "cnpj": [
        "11.222.333/0001-80",
        "11.111.111/1111-11",
        "00000000000000",
        "12.abc.345/01de-35",  # letters must be uppercase
        "12abc34501de05",  # lowercase, with the digits its ASCII values give
        "12.ABC.345/01DE-3A",  # the check digits are digits
        "1122233300018",
    ],
    "gtin": ["4006381333932", "4006381333", "400638133393", "4,00638E+12", "123456789012345"],
}


def reference_digits(values: list[int], weights: list[int], modulus: int) -> int:
    """The weighted sum's remainder, written independently of checkdigits."""
    return sum(v * w for v, w in zip(values, weights, strict=True)) % modulus


def reference_valid(scheme: str, digits: str) -> bool:
    """A plain textbook version of each scheme, for digit strings only."""
    d = [int(ch) for ch in digits]
    if scheme == "cuit":
        r = reference_digits(d[:10], [5, 4, 3, 2, 7, 6, 5, 4, 3, 2], 11)
        return {0: 0, 1: None}.get(r, 11 - r) == d[10]
    if scheme == "cpf":
        if len(set(digits)) == 1:
            return False
        first = reference_digits(d[:9], list(range(10, 1, -1)), 11) * 10 % 11 % 10
        second = reference_digits(d[:10], list(range(11, 1, -1)), 11) * 10 % 11 % 10
        return [first, second] == d[9:]
    total = sum(v * (3 if i % 2 == 0 else 1) for i, v in enumerate(reversed(d[:-1])))
    return (-total) % 10 == d[-1]


# --- the schemes -------------------------------------------------------------


@pytest.mark.parametrize("scheme", sorted(VALID))
def test_published_valid_identifiers(scheme: str) -> None:
    for value in VALID[scheme]:
        assert validator(scheme)(value), value


@pytest.mark.parametrize("scheme", sorted(INVALID))
def test_invalid_identifiers(scheme: str) -> None:
    for value in INVALID[scheme]:
        assert not validator(scheme)(value), value


@pytest.mark.parametrize("scheme", ["cuit", "rut", "gtin"])
def test_every_single_character_substitution_is_caught(scheme: str) -> None:
    # The point of a check digit: one mistyped digit never gives another
    # valid number. (Letters of an alphanumeric CNPJ are tested below.)
    alphabet = "0123456789" + ("K" if scheme == "rut" else "")
    for value in VALID[scheme]:
        for i, ch in enumerate(value):
            if ch not in alphabet and ch != "k":
                continue
            for other in alphabet:
                if other != ch.upper():
                    typo = value[:i] + other + value[i + 1 :]
                    assert not validator(scheme)(typo), (value, typo)


def test_cpf_misses_some_substitutions_by_design() -> None:
    # Each CPF digit maps the remainders 0 and 1 to the same check digit 0, so
    # a substitution that moves a remainder from 0 to 1 keeps both digits: the
    # published scheme's limit. 123.456.789-09 and 223.456.789-09 are both valid.
    assert valid_cpf("123.456.789-09") and valid_cpf("223.456.789-09")
    assert reference_valid("cpf", "22345678909")


def random_valid(scheme: str, length: int, rng: random.Random) -> str:
    """A random valid identifier of ``scheme`` with ``length`` characters (digits only)."""
    while True:
        body = "".join(rng.choice("0123456789") for _ in range(length - 1))
        for check in "0123456789K":
            if validator(scheme)(body + check):
                return body + check


@pytest.mark.parametrize(("scheme", "length"), [("cuit", 11), ("rut", 9), ("rut", 5)])
def test_cuit_and_rut_catch_every_substitution_and_swap(scheme: str, length: int) -> None:
    # Their remainders map to distinct check digits (CUIT has no number for
    # the one that would need 10), so the guarantee holds for any number,
    # not only the published examples: the README states it.
    rng = random.Random(f"{scheme}{length}")
    alphabet = "0123456789K"
    for _ in range(300):
        value = random_valid(scheme, length, rng)
        for i, ch in enumerate(value):
            for other in alphabet if i == length - 1 and scheme == "rut" else alphabet[:10]:
                if other != ch:
                    assert not validator(scheme)(value[:i] + other + value[i + 1 :]), value
            if i < length - 1 and ch != value[i + 1]:
                swapped = value[:i] + value[i + 1] + ch + value[i + 2 :]
                assert not validator(scheme)(swapped), (value, swapped)


def test_cnpj_misses_some_substitutions_by_design() -> None:
    # Like CPF, the remainders 0 and 1 both give the check digit 0.
    assert valid_cnpj("91506159982500") and valid_cnpj("71506159982500")


@pytest.mark.parametrize("scheme", ["cuit", "rut", "cpf", "cnpj"])
def test_adjacent_transpositions_are_caught_by_the_modulo_11_schemes(scheme: str) -> None:
    # On these examples; for CPF and CNPJ it is not guaranteed in general.
    for value in VALID[scheme]:
        compact = [ch for ch in value if ch not in ".-/"]
        for i in range(len(compact) - 1):
            if compact[i] != compact[i + 1]:
                swapped = compact[:]
                swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
                assert not validator(scheme)("".join(swapped)), (value, swapped)


def test_gtin_catches_transpositions_except_of_digits_five_apart() -> None:
    # Modulo 10 with the weights 3 and 1 misses only swaps of two digits that
    # differ by 5 (0 and 5, 3 and 8, ...): 3a + b and a + 3b differ by 2(a - b).
    for value in VALID["gtin"]:
        for i in range(len(value) - 1):
            a, b = value[i], value[i + 1]
            if a != b:
                swapped = value[:i] + b + a + value[i + 2 :]
                assert valid_gtin(swapped) is (abs(int(a) - int(b)) == 5), (value, swapped)
    assert valid_gtin("4006831333931")  # 38 -> 83


@pytest.mark.parametrize("scheme", ["cuit", "cpf", "gtin"])
def test_the_schemes_agree_with_a_textbook_version(scheme: str) -> None:
    lengths = {"cuit": [11], "cpf": [11], "gtin": [8, 12, 13, 14]}[scheme]
    rng = random.Random(247)
    found = 0
    for _ in range(20_000):
        digits = "".join(rng.choice("0123456789") for _ in range(rng.choice(lengths)))
        expected = reference_valid(scheme, digits)
        found += expected
        assert validator(scheme)(digits) is expected, digits
    assert found > 100  # both outcomes were exercised


def test_rut_check_digit_k_and_zero() -> None:
    # 11 - sum % 11 is 10 for K and 11 for 0.
    assert valid_rut("60.803.000-K") and valid_rut("60.803.000-k")
    assert [valid_rut(f"60803000{d}") for d in "0123456789"] == [False] * 10
    zero = next(f"{body}0" for body in range(1, 100) if valid_rut(f"{body}0"))
    assert not valid_rut(zero[:-1] + "K")


def test_cuit_whose_check_digit_would_be_10_is_never_valid() -> None:
    body = next(
        b
        for b in (f"20{n:08d}" for n in range(1000))
        if (
            11
            - sum(int(c) * w for c, w in zip(b, [5, 4, 3, 2, 7, 6, 5, 4, 3, 2], strict=True)) % 11
        )
        == 10
    )
    assert [valid_cuit(body + d) for d in "0123456789"] == [False] * 10


def test_the_alphanumeric_cnpj_uses_ascii_values() -> None:
    # The Receita Federal's example: 12.ABC.345/01DE-35. A letter is worth its
    # ASCII code minus 48 (A = 17), so a digit with the same value differs.
    assert valid_cnpj("12ABC34501DE35")
    assert not valid_cnpj("12ABC34501DF35")
    assert not valid_cnpj("12ÁBC34501DE35")  # only A-Z
    # Modulo 11 cannot tell apart two characters 11 apart (A = 17 and 6,
    # B and 7, L and A, ...): the published scheme's limit, not a bug here.
    assert valid_cnpj("126BC34501DE35") and valid_cnpj("12LBC34501DE35")


def test_only_ascii_digits_count() -> None:
    # str.isdigit accepts superscripts and other scripts' digits; int() of
    # some of them fails and of others gives a digit, so neither is valid.
    assert not valid_cuit("33-69345023-٩")  # ARABIC-INDIC DIGIT NINE
    assert not valid_gtin("400638133393¹")  # SUPERSCRIPT ONE
    assert not valid_cpf("529982247２5")  # FULLWIDTH DIGIT TWO
    assert not valid_rut("11111111-١")


def test_separators_are_ignored_anywhere() -> None:
    assert (
        valid_cuit("33 69345023 9") and valid_cuit("33.69345023.9") and valid_cuit("33/693-45023 9")
    )
    assert valid_cpf("529 982 247 25") and valid_cnpj("11 222 333 0001 81")


def test_check_scheme_and_labels() -> None:
    assert [check_scheme(s) for s in SCHEMES] == ["cuit", "rut", "cpf", "cnpj", "gtin"]
    assert [scheme_label(s) for s in SCHEMES] == ["CUIT", "RUT", "CPF", "CNPJ", "GTIN"]
    message = r"unknown check-digit scheme 'CUIT' \(use one of: cuit, rut, cpf, cnpj, gtin\)"
    with pytest.raises(ValueError, match=message):
        check_scheme("CUIT")
    for bad in ("", "ean", None, ["cuit"]):
        with pytest.raises(ValueError, match="unknown check-digit scheme"):
            validator(bad)  # type: ignore[arg-type]
        # Label lookup is part of the same public scheme API; it should
        # provide the same actionable ValueError instead of a KeyError
        # (or TypeError for an unhashable scheme).
        with pytest.raises(ValueError, match="unknown check-digit scheme"):
            scheme_label(bad)  # type: ignore[arg-type]


# --- measuring in the profile --------------------------------------------------


def iter_rows(make: Callable[[], list[list[str]]]) -> Iterator[list[str]]:
    yield from make()


def measured(path: Path, name: str, scheme: str, top_n: int = 5) -> CheckDigitProfile:
    report = profile_file(
        path, delimiter=";", na_tokens=("s/d",), top_n=top_n, check_digits={name: scheme}
    )
    (found,) = report.check_digits
    return found


def test_invalid_cells_are_counted_exactly(write_csv: WriteCsv) -> None:
    # "s/d" and "" are missing; " 7791234567898 " is stripped and valid.
    path = write_csv(DATA)
    assert measured(path, "CUIT", "cuit") == CheckDigitProfile(
        column="CUIT", scheme="cuit", invalid=2, examples=(("30-71234576-1", 2),)
    )
    assert measured(path, "EAN", "gtin") == CheckDigitProfile(
        column="EAN",
        scheme="gtin",
        invalid=2,
        examples=(("7791234567889", 1), ("7,79123E+12", 1)),
    )
    assert measured(path, "EAN", "gtin", top_n=0).examples == ()
    assert measured(path, "Proveedor", "rut").invalid == 7


def test_build_report_measures_the_same(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    built = build_report(
        read_table(path, delimiter=";"), na_tokens=("s/d",), check_digits={"EAN": "gtin"}
    )
    assert built.check_digits == (measured(path, "EAN", "gtin"),)


def test_no_schemes_no_profiles_and_unprofiled_names_are_skipped(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    assert profile_file(path, delimiter=";").check_digits == ()
    narrow = profile_file(path, delimiter=";", columns=("EAN",), check_digits={"CUIT": "cuit"})
    assert narrow.check_digits == ()


def test_an_unknown_scheme_fails_before_reading(write_csv: WriteCsv) -> None:
    def rows() -> list[list[str]]:
        raise AssertionError("rows were read")

    with pytest.raises(ValueError, match="unknown check-digit scheme 'ean13'"):
        profile_file(write_csv(DATA), delimiter=";", check_digits={"EAN": "ean13"})
    with pytest.raises(ValueError, match="unknown check-digit scheme 'ean13'"):
        profile_rows(["EAN"], iter_rows(rows), check_digits={"EAN": "ean13"})


# --- evaluate() ------------------------------------------------------------------


def test_evaluate_fails_and_describes(write_csv: WriteCsv) -> None:
    schemes = {"CUIT": "cuit", "EAN": "gtin"}
    report = profile_file(write_csv(DATA), delimiter=";", na_tokens=("s/d",), check_digits=schemes)
    cuit, ean = evaluate(report, check_digits=schemes)
    assert (cuit.check, cuit.column, cuit.limit, cuit.value, cuit.passed, cuit.scheme) == (
        CHECK_CHECK_DIGIT,
        "CUIT",
        0,
        2,
        False,
        "cuit",
    )
    assert cuit.describe() == (
        "column 'CUIT' has 2 cells that are not valid CUIT numbers: \"30-71234576-1\" in 2 cells"
    )
    assert ean.describe() == (
        "column 'EAN' has 2 cells that are not valid GTIN numbers: "
        '"7791234567889" in 1 cell, "7,79123E+12" in 1 cell'
    )


def test_evaluate_passes_and_one_cell_without_examples(write_csv: WriteCsv) -> None:
    path = write_csv("CPF;CNPJ\n529.982.247-25;11.222.333/0001-81\n;12.ABC.345/01DE-36\n")
    schemes = {"CPF": "cpf", "CNPJ": "cnpj"}
    report = profile_file(path, delimiter=";", top_n=0, check_digits=schemes)
    cpf, cnpj = evaluate(report, check_digits=schemes)
    assert cpf.passed and cpf.value == 0
    assert cpf.describe() == "column 'CPF' has only valid CPF numbers"
    assert not cnpj.passed
    assert cnpj.describe() == "column 'CNPJ' has 1 cell that is not a valid CNPJ number"


def test_evaluate_needs_the_same_scheme_in_the_report(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA), delimiter=";", check_digits={"CUIT": "cuit"})
    with pytest.raises(ValueError, match="'CUIT' has a check_digit check but the report"):
        evaluate(report, check_digits={"CUIT": "rut"})
    with pytest.raises(ValueError, match="'EAN' has a check_digit check but the report"):
        evaluate(report, check_digits={"EAN": "gtin"})
    with pytest.raises(ValueError, match="unknown check-digit scheme"):
        evaluate(report, check_digits={"CUIT": "nit"})


def test_unknown_and_unprofiled_columns(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    checks = evaluate(profile_file(path, delimiter=";"), check_digits={"CUlT": "cuit"})
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "CUlT", False)
    ]
    narrow = profile_file(path, delimiter=";", columns=("EAN",))
    with pytest.raises(ValueError, match="column 'CUIT' has a per-column check"):
        evaluate(narrow, check_digits={"CUIT": "cuit"})


def test_markdown_escapes_the_examples(write_csv: WriteCsv) -> None:
    path = write_csv("Código\n[x](y)\n`1`\n")
    report = profile_file(path, check_digits={"Código": "gtin"})
    checks = evaluate(report, check_digits={"Código": "gtin"})
    text = render_markdown(report, str(path), checks=checks)
    assert (
        "- FAIL: column 'Código' has 2 cells that are not valid GTIN numbers: "
        '"\\[x\\](y)" in 1 cell, "\\`1\\`" in 1 cell'
    ) in text


# --- command line -------------------------------------------------------------------


def run(write_csv: WriteCsv, *args: str) -> int:
    return main([str(write_csv(DATA)), "--delimiter", "auto", "--na", "s/d", *args])


def test_cli_fails_and_the_last_scheme_wins(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run(write_csv, "--check-digit", "EAN=cuit", "--check-digit", "EAN=gtin")
    out, err = capsys.readouterr()
    assert code == 8
    assert err == (
        "check failed: column 'EAN' has 2 cells that are not valid GTIN numbers: "
        '"7791234567889" in 1 cell, "7,79123E+12" in 1 cell\n'
    )
    assert "CUIT numbers" not in out


def test_cli_passes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv("RUT;Nombre\n76.086.428-5;A\n60.803.000-k;B\n")
    assert main([str(path), "--delimiter", ";", "--check-digit", "RUT=rut"]) == 0
    assert "- pass: column 'RUT' has only valid RUT numbers" in capsys.readouterr().out


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--format", "json", "--check-digit", "CUIT=cuit") == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check == {
        "check": "check_digit",
        "column": "CUIT",
        "limit": 0,
        "value": 2,
        "passed": False,
        "scheme": "cuit",
        "invalid": {"30-71234576-1": 2},
    }


def test_cli_name_ends_at_the_last_equals_sign(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("ID=fiscal;x\n33-69345023-9;1\n")
    assert main([str(path), "--delimiter", ";", "--check-digit", "ID=fiscal=cuit"]) == 0
    assert "column 'ID=fiscal' has only valid CUIT numbers" in capsys.readouterr().out


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json") == 0
    out = capsys.readouterr().out
    assert "check_digit" not in out and "scheme" not in out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--check-digit", "CUIT"], "invalid --check-digit value: 'CUIT' (use NAME=SCHEME"),
        (["--check-digit", "=cuit"], "invalid --check-digit value: '=cuit' (use NAME=SCHEME"),
        (["--check-digit", "CUIT="], "schemes: cuit, rut, cpf, cnpj, gtin)"),
        (
            ["--check-digit", "CUIT=CUIT"],
            "invalid --check-digit value for 'CUIT': unknown check-digit scheme 'CUIT' "
            "(use one of: cuit, rut, cpf, cnpj, gtin)",
        ),
        (["--columns", "EAN", "--check-digit", "CUIT=cuit"], "--check-digit checks column 'CUIT'"),
    ],
)
def test_cli_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(write_csv, *args)
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_cli_unknown_column_fails_as_required(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--check-digit", "Cuit=cuit") == 8
    assert "required column 'Cuit' is missing" in capsys.readouterr().err
