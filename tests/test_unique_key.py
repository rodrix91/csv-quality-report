"""Tests for the ``--unique-key`` gate on composite keys (issue #115)."""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report import KeyProfile
from csv_quality_report.checks import CHECK_REQUIRED_COLUMN, CHECK_UNIQUE_KEY, evaluate
from csv_quality_report.cli import main
from csv_quality_report.profile import _BATCH_ROWS, build_report, key_columns, profile_file
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]
# Invoice lines: F-1 line 1 appears three times (once padded), F-2 line 1
# twice; every invoice and every line number repeats on its own. One row has
# no line number and one has "s/d" as invoice, so neither is checked.
DATA = (
    "Factura;Línea;Monto\n"
    "F-1;1;10\n"
    "F-1;2;20\n"
    " F-1 ;1;30\n"
    "F-2;1;5\n"
    "F-2;;6\n"
    "F-2;1;7\n"
    "s/d;1;8\n"
    "F-1;1;9\n"
    "F-3;1;1\n"
    "f-3;1;2\n"
)
OPTIONS = ["--delimiter", ";", "--na", "s/d"]
KEY = "Factura,Línea"


def checks_json(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, list[dict[str, Any]]]:
    code = main([*args, "--format", "json"])
    checks: list[dict[str, Any]] = json.loads(capsys.readouterr().out)["checks"]
    return code, checks


def test_repeated_key_fails(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code, checks = checks_json(capsys, str(write_csv(DATA)), *OPTIONS, "--unique-key", KEY)
    assert code == 8
    assert checks == [
        {
            "check": "unique_key",
            "column": None,
            "limit": 0,
            "value": 3,
            "passed": False,
            "columns": ["Factura", "Línea"],
            "skipped": 2,
            "repeated": [
                {"key": ["F-1", "1"], "rows": 3},
                {"key": ["F-2", "1"], "rows": 2},
            ],
        }
    ]


def test_messages(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    path = str(write_csv(DATA))
    assert main([path, *OPTIONS, "--unique-key", KEY, "--unique-key", "Factura,Monto"]) == 8
    captured = capsys.readouterr()
    assert captured.err == (
        "check failed: key 'Factura' + 'Línea' is not unique: 3 rows repeat an earlier key "
        '("F-1" + "1" in 3 rows, "F-2" + "1" in 2 rows); '
        "2 rows with a missing key cell were skipped\n"
    )
    assert (
        "- pass: key 'Factura' + 'Monto' has no repeated values; "
        "1 row with a missing key cell was skipped\n"
    ) in captured.out


def test_singular_and_no_skipped_rows(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv("a,b\n1,x\n1,y\n1,x\n"))
    assert main([path, "--unique-key", "a,b"]) == 8
    assert capsys.readouterr().err == (
        "check failed: key 'a' + 'b' is not unique: 1 row repeats an earlier key "
        '("1" + "x" in 2 rows)\n'
    )
    assert main([path, "--unique-key", "b,a", "--max-rows", "2"]) == 0
    assert "- pass: key 'b' + 'a' has no repeated values\n" in capsys.readouterr().out


def test_columns_that_repeat_alone_can_form_a_unique_key(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # Each column repeats on its own, so --unique fails on both; the pair does not.
    path = str(write_csv("Factura,Linea\nF-1,1\nF-1,2\nF-2,1\nF-2,2\n"))
    code, checks = checks_json(
        capsys, path, "--unique", "Factura", "--unique", "Linea", "--unique-key", "Factura,Linea"
    )
    assert code == 8
    assert [(c["check"], c["passed"]) for c in checks] == [
        ("unique", False),
        ("unique", False),
        ("unique_key", True),
    ]
    assert checks[2]["repeated"] == []


def test_rows_with_a_missing_key_cell_are_skipped(write_csv: WriteCsv) -> None:
    # Any missing cell skips the row, even when the other cell repeats a full key.
    path = write_csv("a,b\n1,\n1,\n,2\ns/d,2\n-,-\n1,2\n1, \n")
    (key,) = profile_file(path, na_tokens=("s/d", "-"), unique_keys=[("a", "b")]).keys
    assert key == KeyProfile(columns=("a", "b"), checked=1, skipped=6, repeated=0)
    # Without --na, "s/d" and "-" are values: ("s/d", "2") and ("-", "-") are checked.
    (key,) = profile_file(path, unique_keys=[("a", "b")]).keys
    assert (key.checked, key.skipped, key.repeated) == (3, 4, 0)


def test_values_compare_as_stripped_text(write_csv: WriteCsv) -> None:
    # Padding merges; case, leading zeros and decimal spellings do not.
    path = write_csv('a,b\nA1,7\n"  A1",7 \na1,7\nA1,007\nA1,"7,0"\nA1,7.0\n')
    (key,) = profile_file(path, unique_keys=[("a", "b")]).keys
    assert key.repeated == 1
    assert key.examples == ((("A1", "7"), 2),)


def test_cell_boundaries_are_kept(write_csv: WriteCsv) -> None:
    # The same characters split differently are different keys.
    path = write_csv('a,b\n"x,y",z\nx,"y,z"\nxy,z\nx,yz\nx y,z\nx,y z\n')
    (key,) = profile_file(path, unique_keys=[("a", "b")]).keys
    assert (key.checked, key.repeated) == (6, 0)


def test_examples_follow_top_and_counts_stay_exact(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # Keys found repeated: (b, 1) first, then (a, 1), then (c, 1).
    path = str(write_csv("k,n\nb,1\na,1\nb,1\na,1\na,1\nc,1\nc,1\na,1\n"))
    code, checks = checks_json(capsys, path, "--unique-key", "k,n", "--top", "2")
    assert (code, checks[0]["value"]) == (8, 5)
    # The first two keys found repeated, most rows first.
    assert checks[0]["repeated"] == [{"key": ["a", "1"], "rows": 4}, {"key": ["b", "1"], "rows": 2}]
    assert main([path, "--unique-key", "k,n", "--top", "0"]) == 8
    assert capsys.readouterr().err == (
        "check failed: key 'k' + 'n' is not unique: 5 rows repeat an earlier key\n"
    )


def test_max_rows_counts_only_rows_read(write_csv: WriteCsv) -> None:
    path = write_csv("a,b\n1,1\n1,2\n2,1\n1,1\n")
    (check,) = evaluate(
        profile_file(path, max_rows=3, unique_keys=[["a", "b"]]), unique_keys=[["a", "b"]]
    )
    assert check.passed
    (check,) = evaluate(profile_file(path, unique_keys=[["a", "b"]]), unique_keys=[["a", "b"]])
    assert (check.check, check.value, check.passed) == (CHECK_UNIQUE_KEY, 1, False)


def test_repeats_across_batches(write_csv: WriteCsv) -> None:
    # Keys repeated in a later batch of the streaming pass are caught and counted.
    rows = [f"{n % 7},{n}" for n in range(_BATCH_ROWS + 5)] + ["0,0", "6,6", "0,0"]
    path = write_csv("a,b\n" + "\n".join(rows) + "\n")
    (key,) = profile_file(path, unique_keys=[("a", "b")]).keys
    assert (key.repeated, key.examples) == (3, ((("0", "0"), 3), (("6", "6"), 2)))


def brute_force(rows: list[tuple[str, ...]], na: set[str], top: int) -> KeyProfile:
    """The expected KeyProfile, from a plain scan that keeps every key."""
    seen: set[tuple[str, ...]] = set()
    order: list[tuple[str, ...]] = []  # keys in the order they were found repeated
    counts: Counter[tuple[str, ...]] = Counter()
    skipped = repeated = 0
    for row in rows:
        key = tuple(cell.strip() for cell in row)
        if any(cell in na for cell in key):
            skipped += 1
            continue
        counts[key] += 1
        if key in seen:
            repeated += 1
            if key not in order:
                order.append(key)
        seen.add(key)
    listed = sorted(order[:top], key=lambda key: -counts[key])
    return KeyProfile(
        columns=("a", "b", "c"),
        checked=len(rows) - skipped,
        skipped=skipped,
        repeated=repeated,
        examples=tuple((key, counts[key]) for key in listed),
    )


@pytest.mark.parametrize("seed", range(5))
def test_matches_brute_force(write_csv: WriteCsv, seed: int) -> None:
    # Random padded, missing and repeated cells over more than two batches.
    rng = random.Random(seed)
    tokens = ["", " ", "s/d", "A", " A", "A ", "a", "B", "007", "7", "x,y", '"q"']
    size = rng.randint(1, 3) * _BATCH_ROWS + rng.randint(0, 50)
    rows = [tuple(rng.choice(tokens) for _ in range(3)) for _ in range(size)]
    body = "".join(",".join('"' + c.replace('"', '""') + '"' for c in row) + "\n" for row in rows)
    path = write_csv("a,b,c\n" + body)
    top = rng.randint(0, 5)
    report = profile_file(path, na_tokens=("s/d",), top_n=top, unique_keys=[("a", "b", "c")])
    assert report.keys == (brute_force(rows, {"", "s/d"}, top),)


def test_one_column_key_counts_like_unique(write_csv: WriteCsv) -> None:
    path = write_csv(DATA.replace(";", ","))
    report = profile_file(path, na_tokens=("s/d",), unique_keys=[["Factura"]])
    unique, key = evaluate(report, unique_columns=["Factura"], unique_keys=[["Factura"]])
    assert unique.value == key.value == 5


def test_repeated_keys_and_names_count_once(write_csv: WriteCsv) -> None:
    path = str(write_csv(DATA))
    keys = [("Factura", "Línea"), ("Factura", "Línea", "Factura"), ("Línea", "Factura")]
    report = profile_file(path, delimiter=";", unique_keys=keys)
    assert [key.columns for key in report.keys] == [("Factura", "Línea"), ("Línea", "Factura")]
    checks = evaluate(report, unique_keys=keys)
    assert [check.key for check in checks] == [("Factura", "Línea"), ("Línea", "Factura")]


def test_option_splits_and_strips_names_like_require_columns(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(DATA))
    code, checks = checks_json(
        capsys, path, *OPTIONS, "--unique-key", " Factura , Línea,", "--unique-key", KEY
    )
    assert (code, len(checks), checks[0]["columns"]) == (8, 1, ["Factura", "Línea"])


def test_name_with_a_comma_cannot_be_part_of_a_key(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # Names are split at every comma: "Nro, factura" becomes two unknown names.
    # A single such column is still checked with --unique, which takes the name whole.
    path = str(write_csv('"Nro, factura";Linea\n1;1\n1;1\n'))
    code, checks = checks_json(capsys, path, "--delimiter", ";", "--unique-key", "Nro, factura")
    assert code == 8
    assert [(c["check"], c["column"]) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "Nro"),
        (CHECK_REQUIRED_COLUMN, "factura"),
    ]


@pytest.mark.parametrize("value", ["", " , "])
def test_blank_key_is_usage_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        main([str(write_csv(DATA)), "--unique-key", value])
    assert exc.value.code == 2
    assert f"invalid --unique-key value: {value!r} (no names)" in capsys.readouterr().err


def test_unknown_name_fails_as_required_column(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv('" Factura";Línea\n1;1\n'))
    code, checks = checks_json(
        capsys, path, "--delimiter", ";", "--unique-key", "Factura,Línea,Sucursal"
    )
    assert code == 8
    assert [(c["check"], c["column"]) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "Factura"),
        (CHECK_REQUIRED_COLUMN, "Sucursal"),
    ]
    assert main([path, "--delimiter", ";", "--unique-key", "Factura,Línea"]) == 8
    assert "did you mean ' Factura'?" in capsys.readouterr().err


def test_key_may_use_columns_left_out_by_columns(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # Rows are read whole, so the key is measured although only Monto is profiled.
    path = str(write_csv(DATA))
    code = main([path, *OPTIONS, "--columns", "Monto", "--unique-key", KEY, "--format", "json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 8
    assert [c["name"] for c in report["columns"]] == ["Monto"]
    assert (report["checks"][0]["check"], report["checks"][0]["value"]) == ("unique_key", 3)


def test_default_report_measures_no_key(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv(DATA), delimiter=";").keys == ()


def test_build_report_matches_profile_file(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    keys = [("Factura", "Línea"), ("Factura", "Nope")]
    streamed = profile_file(path, delimiter=";", na_tokens=("s/d",), unique_keys=keys)
    table = read_table(path, delimiter=";")
    assert build_report(table, na_tokens=("s/d",), unique_keys=keys) == streamed
    assert [key.columns for key in streamed.keys] == [("Factura", "Línea")]


def test_api_rejects_a_key_the_report_did_not_measure(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("a,b\n1,2\n"), unique_keys=[("a", "b")])
    with pytest.raises(ValueError, match=r"key \(b, a\) has a unique_key check but was not"):
        evaluate(report, unique_keys=[("b", "a")])


@pytest.mark.parametrize("key", [(), "ab"])
def test_api_rejects_empty_or_string_keys(write_csv: WriteCsv, key: Any) -> None:
    path = write_csv("a,b\n1,2\n")
    with pytest.raises(ValueError, match="unique key"):
        profile_file(path, unique_keys=[key])
    with pytest.raises(ValueError, match="unique key"):
        key_columns(key)
