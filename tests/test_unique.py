"""Tests for the ``--unique`` quality gate on key columns (issue #112)."""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report.checks import CHECK_REQUIRED_COLUMN, CHECK_UNIQUE, evaluate
from csv_quality_report.cli import main
from csv_quality_report.profile import _BATCH_ROWS, profile_file

WriteCsv = Callable[..., Path]
# Factura repeats F-0002 three times (once padded) and F-0007 twice; f-0003 and
# F-0003 differ by case, 007 and 7 by a leading zero; two cells are empty and
# one is "s/d".
DATA = (
    "Factura;Monto;Guia\n"
    "F-0001;10;G1\n"
    "F-0002;20;G2\n"
    " F-0002 ;30;G3\n"
    "F-0003;;G4\n"
    "f-0003;5;G5\n"
    ";6;G6\n"
    "s/d;7;G7\n"
    ";8;G8\n"
    "F-0002;9;G9\n"
    "F-0007;1;G10\n"
    "F-0007;1;G11\n"
    "007;2;G12\n"
    "7;3;G13\n"
)
OPTIONS = ["--delimiter", ";", "--na", "s/d"]


def checks_json(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, list[dict[str, Any]]]:
    code = main([*args, "--format", "json"])
    checks: list[dict[str, Any]] = json.loads(capsys.readouterr().out)["checks"]
    return code, checks


def test_repeated_key_fails(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code, checks = checks_json(capsys, str(write_csv(DATA)), *OPTIONS, "--unique", "Factura")
    assert code == 8
    assert checks == [
        {
            "check": "unique",
            "column": "Factura",
            "limit": 0,
            "value": 3,
            "passed": False,
            "repeated": {"F-0002": 3, "F-0007": 2},
        }
    ]


def test_messages(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    args = [str(write_csv(DATA)), *OPTIONS, "--unique", "Factura", "--unique", "Guia"]
    assert main(args) == 8
    captured = capsys.readouterr()
    assert captured.err == (
        "check failed: column 'Factura' is not unique: 3 cells repeat an earlier value "
        '("F-0002" in 3 cells, "F-0007" in 2 cells)\n'
    )
    assert "- pass: column 'Guia' has no repeated values\n" in captured.out


def test_one_repeat_is_singular(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(write_csv("id\n1\n2\n1\n")), "--unique", "id"]) == 8
    assert capsys.readouterr().err == (
        "check failed: column 'id' is not unique: 1 cell repeats an earlier value "
        '("1" in 2 cells)\n'
    )


def test_unique_column_passes(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code, checks = checks_json(capsys, str(write_csv(DATA)), *OPTIONS, "--unique", "Guia")
    assert code == 0
    assert checks == [
        {
            "check": "unique",
            "column": "Guia",
            "limit": 0,
            "value": 0,
            "passed": True,
            "repeated": {},
        }
    ]


def test_missing_cells_never_repeat(write_csv: WriteCsv) -> None:
    # Three empty cells, two "s/d" and two "-": none of them is a value.
    path = write_csv("id\n\n1\n\ns/d\n2\ns/d\n\n-\n-\n")
    report = profile_file(path, na_tokens=("s/d", "-"))
    (check,) = evaluate(report, unique_columns=["id"])
    assert (check.check, check.value, check.passed) == (CHECK_UNIQUE, 0, True)
    # Without --na, "s/d" and "-" are values, and each repeats once.
    (check,) = evaluate(profile_file(path), unique_columns=["id"])
    assert (check.value, check.repeated) == (2, (("s/d", 2), ("-", 2)))


def test_values_compare_as_stripped_text(write_csv: WriteCsv) -> None:
    # Padding merges; case, leading zeros and decimal spellings do not.
    path = write_csv('id\nA1\n"  A1"\na1\n007\n7\n"1,0"\n1.0\n')
    (check,) = evaluate(profile_file(path), unique_columns=["id"])
    assert (check.value, check.repeated) == (1, (("A1", 2),))


def test_count_is_exact_beyond_top_values(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # --top 1 lists only the most repeated value; the count still includes b.
    path = str(write_csv("id\na\na\na\nb\nb\nc\n"))
    code, checks = checks_json(capsys, path, "--unique", "id", "--top", "1")
    assert (code, checks[0]["value"], checks[0]["repeated"]) == (8, 3, {"a": 3})
    # --top 0 lists none: the message gives the count alone.
    assert main([path, "--unique", "id", "--top", "0"]) == 8
    assert capsys.readouterr().err == (
        "check failed: column 'id' is not unique: 3 cells repeat an earlier value\n"
    )


def test_max_rows_counts_only_rows_read(write_csv: WriteCsv) -> None:
    path = write_csv("id\n1\n2\n3\n1\n")
    (check,) = evaluate(profile_file(path, max_rows=3), unique_columns=["id"])
    assert check.passed
    (check,) = evaluate(profile_file(path), unique_columns=["id"])
    assert not check.passed


def test_repeats_across_batches(write_csv: WriteCsv) -> None:
    # A key repeated in two different batches of the streaming pass is caught.
    rows = [str(n) for n in range(_BATCH_ROWS + 5)] + ["0", "7"]
    path = write_csv("id\n" + "\n".join(rows) + "\n")
    (check,) = evaluate(profile_file(path), unique_columns=["id"])
    assert (check.value, check.repeated) == (2, (("0", 2), ("7", 2)))


def test_matches_brute_force_count(write_csv: WriteCsv) -> None:
    rng = random.Random(112)
    tokens = ["", " ", "s/d", "A", " A", "A ", "a", "B", "007", "7", "C", "D", "E"]
    for _ in range(50):
        cells = [rng.choice(tokens) for _ in range(rng.randint(0, 30))]
        path = write_csv("id,n\n" + "".join(f'"{cell}",1\n' for cell in cells))
        (check,) = evaluate(profile_file(path, na_tokens=("s/d",)), unique_columns=["id"])
        values = Counter(c.strip() for c in cells if c.strip() not in ("", "s/d"))
        expected = sum(count - 1 for count in values.values())
        assert check.value == expected, cells
        assert check.passed == (expected == 0)
        assert set(check.repeated) <= {(v, n) for v, n in values.items() if n > 1}


def test_repeated_name_gives_one_check(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("id,x\n1,2\n"))
    checks = evaluate(report, unique_columns=["id", "x", "id"])
    assert [check.column for check in checks] == ["id", "x"]


def test_unknown_name_fails_as_required_column(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(DATA))
    code, checks = checks_json(capsys, path, *OPTIONS, "--unique", " Factura")
    assert code == 8
    assert [(c["check"], c["column"], c["passed"]) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, " Factura", False)
    ]
    assert main([path, *OPTIONS, "--unique", "factura"]) == 8
    err = capsys.readouterr().err
    assert "required column 'factura' is missing" in err
    assert "did you mean" not in err
    assert main([path, *OPTIONS, "--unique", " Factura"]) == 8
    assert "did you mean 'Factura'?" in capsys.readouterr().err


def test_name_is_taken_as_written(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    # Commas and "=" are part of the name, unlike in --require-columns or NAME=N options.
    path = str(write_csv('"Nro, factura";"a=b"\n1;x\n1;x\n'))
    code, checks = checks_json(
        capsys, path, "--delimiter", ";", "--unique", "Nro, factura", "--unique", "a=b"
    )
    assert code == 8
    assert [(c["column"], c["value"]) for c in checks] == [("Nro, factura", 1), ("a=b", 1)]


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_name_is_usage_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        main([str(write_csv(DATA)), "--unique", value])
    assert exc.value.code == 2
    assert f"invalid --unique value: {value!r} (no name)" in capsys.readouterr().err


def test_column_left_out_by_columns(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(DATA))
    with pytest.raises(SystemExit) as exc:
        main([path, *OPTIONS, "--columns", "Monto", "--unique", "Factura"])
    assert exc.value.code == 2
    assert "--unique checks column 'Factura', which --columns leaves out" in (
        capsys.readouterr().err
    )
    code, checks = checks_json(capsys, path, *OPTIONS, "--columns", "Guia", "--unique", "Guia")
    assert (code, checks[0]["passed"]) == (0, True)


def test_api_rejects_unprofiled_column(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv("id,x\n1,2\n"), columns=["x"])
    with pytest.raises(ValueError, match="column 'id' has a per-column check but was not"):
        evaluate(report, unique_columns=["id"])


def test_markdown_lists_the_check(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(write_csv(DATA)), *OPTIONS, "--unique", "Factura"]) == 8
    out = capsys.readouterr().out
    assert "## Checks: FAILED (1 of 1 failed)\n" in out
    assert (
        "- FAIL: column 'Factura' is not unique: 3 cells repeat an earlier value "
        '("F-0002" in 3 cells, "F-0007" in 2 cells)\n' in out
    )
