"""Tests for type hints on mostly-typed string columns (issue #43)."""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report import profile
from csv_quality_report.cli import main
from csv_quality_report.inference import infer_type, value_type
from csv_quality_report.profile import _HINT_PROBE, _type_hint, build_report, profile_file
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]

EDGE_CASES = [
    "0",
    "-0",
    "+7",
    "007",
    "1.",
    ".5",
    "-.5",
    "+1.5e3",
    "1e5",
    "1E-5",
    "1e",
    "e5",
    "1.2.3",
    ",5",
    "5,",
    "1,5",
    "1,5e3",
    "1,2,3",
    "1.234,5",
    "1e999",
    "9" * 700,
    "9" * 5000,
    "true",
    "TRUE",
    "False",
    "tru",
    "t",
    "f",
    "yes",
    "T",
    "Z",
    "-",
    "+",
    ".",
    ",",
    "e",
    "E",
    "2026-01-01",
    "2026-02-30",
    "2026-1-1",
    "20260101",
    "2026-01-01T10:00",
    "2026-01-01 10:00",
    "2026-01-01T10:00:00Z",
    "2026-01-01T10:00:00.123456+04:00",
    "2026-01-01T10:00+0400",
    "2026-01-01T10:00-04",
    "2026-01-01T24:00",
    "2026-01-01t10:00",
    "2026-01-01T10",
    "12 units",
    "12-345-AB",
    "N/A",
    "s/d",
    "La Paz",
    "AR ",
    "1 000",
    "10:30",
    "--1",
    "+-1",
]
ALPHABET = "0123456789+-.,:eETZ tTrRuUfFaAlLsSx/"


def random_values(n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    values = []
    for _ in range(n):
        size = rng.randint(1, 12)
        values.append("".join(rng.choice(ALPHABET) for _ in range(size)).strip() or "0")
    # Mutations of real typed values exercise the boundaries of each pattern.
    for base in ("2026-10-05T14:30:00+04:00", "-12.5e3", "1,25", "true", "2024-02-29"):
        for _ in range(200):
            chars = list(base)
            chars[rng.randrange(len(chars))] = rng.choice(ALPHABET)
            values.append("".join(chars).strip() or "0")
    return values


@pytest.mark.parametrize("decimal_comma", [False, True])
def test_value_type_matches_infer_type_exactly(decimal_comma: bool) -> None:
    for value in EDGE_CASES + random_values(20_000, seed=43):
        assert value_type(value, decimal_comma) == infer_type([value], decimal_comma), value


def column(
    path: Path, capsys: pytest.CaptureFixture[str], name: str, *extra: str
) -> dict[str, Any]:
    assert main([str(path), "--format", "json", *extra]) == 0
    cols = {c["name"]: c for c in json.loads(capsys.readouterr().out)["columns"]}
    found: dict[str, Any] = cols[name]
    return found


def numbers_with(strays: list[str], n: int = 40) -> str:
    return "q\n" + "".join(f"{i}\n" for i in range(n)) + "".join(f"{s}\n" for s in strays)


def test_int_column_with_strays(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    col = column(write_csv(numbers_with(["N/A", "12a", "N/A"])), capsys, "q")
    assert col["type"] == "string"  # inference stays strict
    assert col["type_hint"] == {
        "type": "int",
        "conforming_pct": 93.02,  # 40 of 43, rounded down
        "nonconforming": 3,
        "examples": ["N/A", "12a"],  # most frequent first
    }


def test_ints_and_floats_suggest_float(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    data = "x\n" + "".join(f"{i}\n" for i in range(20)) + "".join(f"{i}.5\n" for i in range(20))
    col = column(write_csv(data + "bad\n"), capsys, "x")
    assert (col["type_hint"]["type"], col["type_hint"]["nonconforming"]) == ("float", 1)


def test_dates_and_datetimes_suggest_datetime(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    data = "d\n" + "2026-01-01\n" * 10 + "2026-01-01T10:00\n" * 10 + "sin fecha\n"
    assert column(write_csv(data), capsys, "d")["type_hint"]["type"] == "datetime"


def test_dates_with_a_stray_suggest_date(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    data = "d\n" + "".join(f"2026-01-{i:02d}\n" for i in range(1, 29)) + "pendiente\n"
    hint = column(write_csv(data), capsys, "d")["type_hint"]
    assert (hint["type"], hint["examples"]) == ("date", ["pendiente"])


def test_below_ninety_percent_gives_no_hint(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # 9 numbers, 1 stray: exactly 90% conforms and gets a hint; 8 of 10 does not.
    assert column(write_csv(numbers_with(["x"], 9)), capsys, "q")["type_hint"] is not None
    assert column(write_csv(numbers_with(["x", "y"], 8)), capsys, "q")["type_hint"] is None


def test_typed_and_text_columns_have_no_hint(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("n,s\n1,La Paz\n2,Tarija\n")
    assert column(path, capsys, "n")["type_hint"] is None
    assert column(path, capsys, "s")["type_hint"] is None


def test_hint_respects_decimal_comma_and_na(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    data = "p\n" + "".join(f"{i},5\n" for i in range(30)) + "NA\n" + "s/d\n"
    path = write_csv(data)
    col = column(path, capsys, "p", "--delimiter", ";", "--decimal-comma", "--na", "NA")
    assert col["type_hint"]["examples"] == ["s/d"]  # NA is missing, not a stray


def test_nearly_all_conforming_never_shows_100(write_csv: WriteCsv) -> None:
    rows = "".join(f"{i}\n" for i in range(20_000))
    hint = profile_file(write_csv("n\n" + rows + "x\n")).columns[0].type_hint
    assert hint is not None and hint.conforming_pct == 99.99


def test_probe_boundary_and_bulk_phase_agree() -> None:
    # Strays placed before, at and after the one-by-one probe give the same hint.
    for position in (0, _HINT_PROBE - 1, _HINT_PROBE, 5 * _HINT_PROBE):
        keys = [str(i) for i in range(20 * _HINT_PROBE)]
        keys.insert(position, "N/A")
        hint = _type_hint(Counter(dict.fromkeys(keys, 1)), False)
        assert hint is not None and hint.examples == ("N/A",), position


def test_text_column_is_rejected_during_the_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    # Plain text past 10% of the cells (2,000 of 12,000) stops the search
    # before the bulk phase: only the first few values are classified.
    calls = 0

    def counting_value_type(value: str, decimal_comma: bool = False) -> str:
        nonlocal calls
        calls += 1
        return value_type(value, decimal_comma)

    monkeypatch.setattr(profile, "value_type", counting_value_type)
    counts = Counter({f"name {i}": 200 for i in range(10)})
    counts.update({str(i): 1 for i in range(10 * _HINT_PROBE)})
    assert _type_hint(counts, False) is None
    assert calls <= 10


def test_markdown_line(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    data = "q|d\n" + "".join(f"{i}|2026-01-01\n" for i in range(30)) + "N/A|x\n"
    assert main([str(write_csv(data.replace("|", ",")))]) == 0
    out = capsys.readouterr().out
    assert (
        '- Mostly typed: q is int except 1 value ("N/A"); d is date except 1 value ("x")\n' in out
    )
    assert main([str(write_csv("a\n1\n"))]) == 0
    assert "Mostly typed" not in capsys.readouterr().out


def test_streaming_and_in_memory_agree(write_csv: WriteCsv) -> None:
    path = write_csv(numbers_with(["N/A"]))
    assert profile_file(path) == build_report(read_table(path))
