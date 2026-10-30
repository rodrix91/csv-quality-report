"""Tests for ``--na-ignore-case`` (issue #231)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.cli import main
from csv_quality_report.compare import load_baseline
from csv_quality_report.profile import build_report, profile_file, profile_rows
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]
# A weight column whose gaps are written in three cases, one padded; a code
# column with a real padded value; a status column with Unicode words.
MIXED = (
    "guia;peso;estado\n"
    "A1;1,5;Entregado\n"
    "A2;S/D;SIN DATO\n"
    "S/d;s/d;Pendiente\n"
    " A4 ; S/D ;Sin Dato\n"
    "A5;2,25;Entregado\n"
)


def report_json(path: Path, capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *args]) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    return report


def test_api_needs_na_tokens(write_csv: WriteCsv) -> None:
    path = write_csv(MIXED)
    message = "na_ignore_case needs na_tokens"
    with pytest.raises(ValueError, match=message):
        profile_file(path, delimiter=";", na_ignore_case=True)
    with pytest.raises(ValueError, match=message):
        build_report(read_table(path, delimiter=";"), na_ignore_case=True)
    # Raised before any row is read; blank tokens count as none.
    with pytest.raises(ValueError, match=message):
        profile_rows(["a"], iter(()), na_tokens=(" ",), na_ignore_case=True)


def test_markers_match_in_any_case(write_csv: WriteCsv) -> None:
    path = write_csv(MIXED)
    report = profile_file(
        path, delimiter=";", decimal_comma=True, na_tokens=("s/d", "sin dato"), na_ignore_case=True
    )
    guia, peso, estado = report.columns
    assert report.na_ignore_case
    assert (peso.type, peso.missing, peso.min, peso.max) == ("float", 3, 1.5, 2.25)
    # The padded marker is missing, not an untrimmed value.
    assert peso.untrimmed == 0
    # Words fold too, and a real padded value is still counted as untrimmed.
    assert (estado.missing, estado.distinct) == (2, 2)
    assert (guia.missing, guia.untrimmed, guia.distinct) == (1, 1, 4)
    same = build_report(
        read_table(path, delimiter=";"),
        decimal_comma=True,
        na_tokens=("s/d", "sin dato"),
        na_ignore_case=True,
    )
    assert same == report


def test_unicode_case_folding(write_csv: WriteCsv) -> None:
    # casefold, not lower: the German sharp s folds to "ss".
    path = write_csv("x\nSTRASSE\nstraße\n5\n")
    col = profile_file(path, na_tokens=("Straße",), na_ignore_case=True).columns[0]
    assert (col.type, col.missing) == ("int", 2)


def test_without_the_option_matching_is_exact(write_csv: WriteCsv) -> None:
    path = write_csv(MIXED)
    report = profile_file(path, delimiter=";", decimal_comma=True, na_tokens=("s/d", "sin dato"))
    guia, peso, estado = report.columns
    assert not report.na_ignore_case
    assert (peso.type, peso.missing, peso.untrimmed) == ("string", 1, 1)
    assert (guia.missing, estado.missing) == (0, 0)


def test_unique_key_skips_markers_in_any_case(write_csv: WriteCsv) -> None:
    path = write_csv("suc;nro\nS/D;1\ns/d;1\nA;1\nA;1\n")
    keys = [("suc", "nro")]
    exact = profile_file(path, delimiter=";", na_tokens=("s/d",), unique_keys=keys).keys[0]
    assert (exact.checked, exact.skipped, exact.repeated) == (3, 1, 1)
    folded = profile_file(
        path, delimiter=";", na_tokens=("s/d",), unique_keys=keys, na_ignore_case=True
    ).keys[0]
    assert (folded.checked, folded.skipped, folded.repeated) == (2, 2, 1)


def test_allowed_values_and_patterns_leave_markers_out(write_csv: WriteCsv) -> None:
    path = write_csv("estado;cp\nok;1234\nN/D;n/d\nn/d;N/d\n")
    report = profile_file(
        path,
        delimiter=";",
        na_tokens=("n/d",),
        na_ignore_case=True,
        allowed_values={"estado": ["ok"]},
        patterns={"cp": "[0-9]{4}"},
    )
    assert (report.domains[0].unexpected, report.patterns[0].mismatched) == (0, 0)
    exact = profile_file(
        path,
        delimiter=";",
        na_tokens=("n/d",),
        allowed_values={"estado": ["ok"]},
        patterns={"cp": "[0-9]{4}"},
    )
    assert (exact.domains[0].unexpected, exact.patterns[0].mismatched) == (1, 1)


def test_json_key_only_with_the_option(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # Every marker is lower case, so the option changes nothing but the key.
    path = write_csv("a;b\n1;s/d\ns/d;2\n")
    plain = report_json(path, capsys, "--delimiter", ";", "--na", "s/d")
    assert "na_ignore_case" not in plain
    folded = report_json(path, capsys, "--delimiter", ";", "--na", "s/d", "--na-ignore-case")
    assert folded["na_ignore_case"] is True
    keys = list(folded)
    assert keys.index("na_ignore_case") == keys.index("na_tokens") + 1
    del folded["na_ignore_case"]
    assert folded == plain


def test_markdown_line(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_csv(MIXED)
    args = [str(path), "--delimiter", ";", "--na", "s/d"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "- Also counted as missing: `s/d`\n" in out
    assert main([*args, "--na-ignore-case"]) == 0
    assert "- Also counted as missing: `s/d` (any case)\n" in capsys.readouterr().out


def test_cli_needs_na(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([str(write_csv(MIXED)), "--delimiter", ";", "--na-ignore-case"])
    assert exc.value.code == 2
    assert "--na-ignore-case needs --na" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("token", "cell"),
    [
        ("sin información", "SIN INFORMACIO\u0301N"),
        ("sin informacio\u0301n", "SIN INFORMACIÓN"),
    ],
)
def test_casefold_matching_also_respects_canonical_unicode(
    write_csv: WriteCsv, token: str, cell: str
) -> None:
    path = write_csv(f"peso\n1\n  {cell}  \n2\n")
    exact = profile_file(path, na_tokens=(token,))
    assert (exact.columns[0].type, exact.columns[0].missing, exact.columns[0].untrimmed) == (
        "string", 0, 1
    )
    folded = profile_file(path, na_tokens=(token,), na_ignore_case=True)
    assert (folded.columns[0].type, folded.columns[0].missing, folded.columns[0].untrimmed) == (
        "int", 1, 0
    )


def test_canonical_na_markers_exclude_composite_keys(write_csv: WriteCsv) -> None:
    path = write_csv(
        "guia;zona\n"
        "A;1\n"
        "SIN INFORMACIO\u0301N;2\n"
        "sin información;3\n"
        "A;4\n"
    )
    keys = [("guia", "zona"), ("guia",)]
    default = profile_file(path, delimiter=";", na_tokens=("sin información",), unique_keys=keys)
    assert [(key.checked, key.skipped, key.repeated) for key in default.keys] == [
        (3, 1, 0), (3, 1, 1)
    ]
    folded = profile_file(
        path, delimiter=";", na_tokens=("sin información",),
        na_ignore_case=True, unique_keys=keys,
    )
    assert [(key.checked, key.skipped, key.repeated) for key in folded.keys] == [
        (2, 2, 0), (2, 2, 1)
    ]


def test_canonical_na_markers_do_not_fail_domains_or_patterns(write_csv: WriteCsv) -> None:
    path = write_csv(
        "estado;codigo\n"
        "OK;1234\n"
        "sin informacio\u0301n;SIN INFORMACIO\u0301N\n"
    )
    extra = {
        "delimiter": ";",
        "na_tokens": ("SIN INFORMACIÓN",),
        "allowed_values": {"estado": ["OK"]},
        "patterns": {"codigo": r"[0-9]{4}"},
    }
    exact = profile_file(path, **extra)
    assert (exact.domains[0].unexpected, exact.patterns[0].mismatched) == (1, 1)
    folded = profile_file(path, na_ignore_case=True, **extra)
    assert (folded.domains[0].unexpected, folded.patterns[0].mismatched) == (0, 0)


def test_cli_canonical_missing_marker_type_gate(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("peso\n1\nSIN INFORMACIO\u0301N\n2\n")
    args = [str(path), "--na", "sin información", "--require-type", "peso=int"]
    assert main([*args, "--na-ignore-case"]) == 0
    capsys.readouterr()
    assert main(args) == 8
    capsys.readouterr()


def test_report_serves_as_baseline(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(MIXED)
    report = tmp_path / "report.json"
    args = [str(path), "--delimiter", ";", "--decimal-comma", "--na", "s/d", "--na-ignore-case"]
    assert main([*args, "--json-output", str(report)]) == 0
    baseline = load_baseline(report)
    assert baseline["na_ignore_case"] is True
    assert baseline["columns"][1]["type"] == "float"
    assert main([*args, "--baseline", str(report), "--fail-on-schema-change"]) == 0
    # Exact matching keeps the weights as text: a type change since the baseline.
    assert main([*args[:-1], "--baseline", str(report), "--fail-on-schema-change"]) == 8
    capsys.readouterr()
