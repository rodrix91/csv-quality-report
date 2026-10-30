"""One-shot missing-token iterables must behave like reusable tuples."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from csv_quality_report.profile import build_report, profile_file, profile_rows
from csv_quality_report.reader import read_table

WriteCsv = Callable[..., Path]

CSV = (
    "sku,qty\n"
    "A1,7\n"
    "A2,S/D\n"
    "A3, s/d \n"
    "A4,2\n"
)


@pytest.mark.parametrize("fold", [False, True])
def test_direct_profile_rows_does_not_consume_token_generator_during_check(fold: bool) -> None:
    rows = [["A1", "7"], ["A2", "S/D"], ["A3", " s/d "], ["A4", "2"]]
    expected = profile_rows(["sku", "qty"], iter(rows), na_tokens=("s/d",), na_ignore_case=fold)
    actual = profile_rows(
        ["sku", "qty"], iter(rows), na_tokens=(s for s in ["s/d"]), na_ignore_case=fold
    )
    assert actual == expected
    assert (actual.columns[1].missing, actual.columns[1].type) == (
        2 if fold else 1,
        "int" if fold else "string",
    )


@pytest.mark.parametrize("fold", [False, True])
def test_generator_preserves_report_metadata_for_stream_and_memory(
    write_csv: WriteCsv, fold: bool
) -> None:
    path = write_csv(CSV)
    expected = profile_file(path, na_tokens=("s/d",), na_ignore_case=fold)
    streamed = profile_file(path, na_tokens=(t for t in ["s/d"]), na_ignore_case=fold)
    in_memory = build_report(
        read_table(path), na_tokens=(t for t in ["s/d"]), na_ignore_case=fold
    )
    assert streamed == expected
    assert in_memory == expected
    assert streamed.na_tokens == in_memory.na_tokens == ("s/d",)


def test_generator_matches_unicode_folded_marker_in_all_three_paths(write_csv: WriteCsv) -> None:
    path = write_csv("qty\n5\nSIN INFORMACIO\u0301N\n9\n")
    marker = "sin información"
    expected = profile_file(path, na_tokens=(marker,), na_ignore_case=True)
    streamed = profile_file(path, na_tokens=(x for x in [marker]), na_ignore_case=True)
    in_memory = build_report(
        read_table(path), na_tokens=(x for x in [marker]), na_ignore_case=True
    )
    direct = profile_rows(
        ["qty"], [["5"], ["SIN INFORMACIO\u0301N"], ["9"]],
        na_tokens=(x for x in [marker]), na_ignore_case=True,
    )
    assert streamed == in_memory == expected
    assert expected.columns[0].missing == direct.columns[0].missing == 1
    assert expected.columns[0].type == direct.columns[0].type == "int"
    assert streamed.na_tokens == (marker,)


def test_one_shot_tokens_are_applied_to_composite_key_missingness(write_csv: WriteCsv) -> None:
    path = write_csv("sku,region\nA,1\nS/D,1\ns/d,1\nA,1\n")
    keys = [("sku", "region")]
    expected = profile_file(
        path, na_tokens=("s/d",), na_ignore_case=True, unique_keys=keys
    )
    actual = profile_file(
        path, na_tokens=(x for x in ["s/d"]), na_ignore_case=True,
        unique_keys=keys,
    )
    assert actual.keys == expected.keys
    assert (actual.keys[0].checked, actual.keys[0].skipped, actual.keys[0].repeated) == (
        2, 2, 1
    )


def test_blank_one_shot_tokens_rejected_before_rows_are_consumed() -> None:
    def unreadable_rows() -> Iterable[list[str]]:
        raise AssertionError("invalid options must not read input rows")
        yield ["x"]

    with pytest.raises(ValueError, match="na_ignore_case needs na_tokens"):
        profile_rows(
            ["x"], unreadable_rows(), na_tokens=(x for x in [" ", ""]),
            na_ignore_case=True,
        )
